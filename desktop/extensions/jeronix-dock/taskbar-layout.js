// SPDX-License-Identifier: GPL-3.0-or-later
//
// Layout of the Windows 11 taskbar row: the app group (Start, Search, Task
// View, apps) centered on the whole bar, or at its start, and the system
// tray pinned to the right end. Positions are computed on every allocation,
// so the group stays centered when the tray changes width (indicators
// appearing, the clock's text changing).

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';

import {taskbarRow} from './geometry.js';

export const TaskbarLayout = GObject.registerClass(
class TaskbarLayout extends Clutter.LayoutManager {
    constructor(group, tray, centered) {
        super();
        this._group = group;
        this._tray = tray;
        this._centered = centered;
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
            min += m;
            nat += n;
        }
        return [min, nat];
    }

    vfunc_get_preferred_height(container, forWidth) {
        let min = 0, nat = 0;
        for (const actor of [this._group, this._tray]) {
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
        const size = actor => {
            if (!this._visible(actor))
                return [0, 0];
            const [, w] = actor.get_preferred_width(-1);
            const [, h] = actor.get_preferred_height(w);
            return [w, Math.min(h, height)];
        };
        const [groupW, groupH] = size(this._group);
        const [trayW, trayH] = size(this._tray);
        const row = taskbarRow({width, groupWidth: groupW, trayWidth: trayW, centered: this._centered});
        const place = (actor, x, w, h) => {
            if (!this._visible(actor))
                return;
            const child = new Clutter.ActorBox();
            const y = box.y1 + Math.round((height - h) / 2);
            child.set_origin(box.x1 + x, y);
            child.set_size(w, h);
            actor.allocate(child);
        };
        place(this._group, row.groupX, row.groupWidth, groupH);
        place(this._tray, row.trayX, trayW, trayH);
    }
});
