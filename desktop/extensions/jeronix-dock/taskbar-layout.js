// SPDX-License-Identifier: GPL-3.0-or-later
//
// Layout of the Windows 11 taskbar row: the app group (Start, Search, Task
// View, apps) centered on the whole bar, or at its start, the system tray
// pinned to the right end, and the live updates in the free space at the
// left (or after a left-aligned group). Positions are computed on every
// allocation, so the group stays centered when the tray or the live updates
// change width (indicators appearing, a longer update).
//
// In the modules style each of the three parts sits on its own module (a
// background drawn behind it, with some padding around it). A module can
// expand toward the panel that opens from it (setExpanded): its background
// grows from its outer side, animated, while the content stays in place.

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {TRAY_GAP, moduleSpan, taskbarRow} from './geometry.js';

export const EXPAND_MS = 220;

export const TaskbarLayout = GObject.registerClass(
class TaskbarLayout extends Clutter.LayoutManager {
    /**
     * @param {Clutter.Actor} group - Start, Search, Task View and the apps
     * @param {Clutter.Actor} tray - Quick Settings and the clock, or null
     * @param {boolean} centered - the group centered (else at the start)
     * @param {Clutter.Actor} live - the live updates, or null
     * @param {object} modules - {left, center, right} module backgrounds
     *   (children of the same container, below the content), or null
     * @param {number} padding - space between a module's edge and its content
     */
    constructor(group, tray, centered, live = null, modules = null, padding = 0) {
        super();
        this._group = group;
        this._tray = tray;
        this._centered = centered;
        this._live = live;
        this._modules = modules;
        this._padding = modules ? padding : 0;
        // side -> {wanted, progress, timeline}
        this._expansion = {};
        this.rects = {left: null, center: null, right: null};
        this.livePlaced = false;
    }

    _visible(actor) {
        return actor && actor.get_parent() && actor.visible;
    }

    vfunc_get_preferred_width(container, forHeight) {
        let min = 0, nat = 0;
        for (const actor of [this._group, this._tray]) {
            if (!this._visible(actor))
                continue;
            const [m, n] = actor.get_preferred_width(forHeight);
            min += m + 2 * this._padding;
            nat += n + 2 * this._padding;
        }
        return [min, nat];
    }

    vfunc_get_preferred_height(container, forWidth) {
        let min = 0, nat = 0;
        for (const actor of [this._group, this._tray, this._live]) {
            if (!this._visible(actor))
                continue;
            const [m, n] = actor.get_preferred_height(-1);
            min = Math.max(min, m);
            nat = Math.max(nat, n);
        }
        return [min, nat];
    }

    vfunc_allocate(container, box) {
        const width = box.get_width();
        const height = box.get_height();
        const pad = this._padding;
        const size = actor => {
            if (!this._visible(actor))
                return [0, 0];
            const [, w] = actor.get_preferred_width(-1);
            const [, h] = actor.get_preferred_height(w);
            return [w, Math.min(h, height)];
        };
        const [groupW, groupH] = size(this._group);
        const [trayW, trayH] = size(this._tray);
        const [liveW, liveH] = size(this._live);
        // Each part takes its content's width plus the module's padding.
        const outer = w => w > 0 ? w + 2 * pad : 0;
        const row = taskbarRow({width, groupWidth: outer(groupW), trayWidth: outer(trayW),
            centered: this._centered, liveWidth: outer(liveW)});
        const place = (actor, x, w, h) => {
            if (!actor)
                return;
            const child = new Clutter.ActorBox();
            const y = box.y1 + Math.round((height - h) / 2);
            child.set_origin(box.x1 + x, y);
            child.set_size(Math.max(0, w), Math.max(0, h));
            actor.allocate(child);
        };
        const groupInner = Math.max(0, row.groupWidth - 2 * pad);
        if (this._visible(this._group))
            place(this._group, row.groupX + pad, groupInner, groupH);
        if (this._visible(this._tray))
            place(this._tray, row.trayX + pad, trayW, trayH);
        // Without room the live updates get no area (and so no clicks).
        this.livePlaced = row.liveX !== null && this._visible(this._live);

        this.rects = {
            left: this.livePlaced ? [row.liveX, outer(liveW)] : null,
            center: this._visible(this._group) ? [row.groupX, row.groupWidth] : null,
            right: this._visible(this._tray) ? [row.trayX, outer(trayW)] : null,
        };
        this._origin = [box.x1, box.y1];
        this._width = width;
        this._height = height;
        if (this._live) {
            // The live updates fill their module, growing with it as it
            // expands toward the widgets (never a small pill on a big module).
            const span = this.livePlaced ? this._currentSpan('left') : null;
            if (span)
                place(this._live, span[0] + pad, Math.max(liveW, span[1] - 2 * pad), liveH);
            else
                place(this._live, 0, 0, liveH);
        }
        if (!this._modules)
            return;
        for (const side of ['left', 'center', 'right']) {
            const backdrop = this._modules[side];
            if (!backdrop)
                continue;
            const rect = this.rects[side];
            if (!rect) {
                place(backdrop, 0, 0, 0);
                continue;
            }
            const [x, w] = this._currentSpan(side);
            place(backdrop, x, w, height);
        }
    }

    // -- expansion -------------------------------------------------------------

    /** [x, width] of a module now (part way through an expansion, maybe). */
    _currentSpan(side) {
        const rest = this.rects[side];
        const e = this._expansion[side];
        if (!rest || !e || e.progress <= 0)
            return rest;
        const [ex, ew] = moduleSpan(this.rects, side, e.wanted, TRAY_GAP, this._width);
        const p = Math.min(1, e.progress);
        return [rest[0] + (ex - rest[0]) * p, rest[1] + (ew - rest[1]) * p];
    }

    /**
     * The rectangle a module will have once expanded toward a panel of
     * width wanted, in the container's coordinates: [x, y, width, height].
     */
    targetRect(side, wanted) {
        if (!this.rects[side])
            return null;
        const [x, w] = moduleSpan(this.rects, side, wanted, TRAY_GAP, this._width);
        return [this._origin[0] + x, this._origin[1], w, this._height];
    }

    /** Grows (wanted > 0) or shrinks back (wanted = 0) the module on side. */
    setExpanded(container, side, wanted) {
        const e = this._expansion[side] ??= {wanted: 0, progress: 0, timeline: null};
        if (!Number.isFinite(wanted))
            return; // never let a bad measurement into the layout
        if (wanted > 0)
            e.wanted = wanted;
        const from = e.progress;
        const to = wanted > 0 ? 1 : 0;
        e.timeline?.stop();
        e.timeline = null;
        if (!St.Settings.get().enable_animations || !container.mapped) {
            e.progress = to;
            this.layout_changed();
            return;
        }
        const timeline = new Clutter.Timeline({actor: container,
            duration: Math.max(1, Math.round(EXPAND_MS * Math.abs(to - from)))});
        timeline.set_progress_mode(Clutter.AnimationMode.EASE_OUT_QUAD);
        timeline.connect('new-frame', () => {
            e.progress = from + (to - from) * timeline.get_progress();
            this.layout_changed();
        });
        timeline.connect('stopped', (t, finished) => {
            if (finished) {
                e.progress = to;
                this.layout_changed();
            }
            if (e.timeline === timeline)
                e.timeline = null;
        });
        e.timeline = timeline;
        timeline.start();
    }

    /** How far each module is expanded (0..1), for tests. */
    get expansion() {
        return Object.fromEntries(Object.entries(this._expansion).map(([side, e]) => [side, e.progress]));
    }

    destroy() {
        for (const e of Object.values(this._expansion)) {
            e.timeline?.stop();
            e.timeline = null;
        }
    }
});
