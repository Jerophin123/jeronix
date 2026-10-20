// SPDX-License-Identifier: GPL-3.0-or-later
//
// Expanding taskbar modules (the 'modules' style). The taskbar is three
// floating modules: live updates and widgets on the left, Start and the
// apps in the center, the Control Center and notifications on the right.
// A panel opening from a module (the widgets, Start, the Control Center,
// the notification center) is drawn as that module expanding: the module
// grows toward the panel's width (TaskbarLayout.setExpanded), the panel
// stands directly on it, and where their edges meet their corners are
// square, so the two read as one shape.
//
// The widgets and Start menus point at an invisible anchor their owners
// place over the expanded module (anchorFor). GNOME's own Quick Settings and
// date menus keep pointing at their buttons, so every GNOME behaviour of
// those buttons stays as it is; the stylesheet keeps them flush with the
// right module (-arrow-rise is the module margin, which GNOME also keeps
// from the screen edge). GNOME insets a panel by that same -arrow-rise from
// the point it opens at; the gap set at opening (which may be negative)
// cancels that and any space between a button and the module's top edge,
// so every panel stands exactly on its module.

import Clutter from 'gi://Clutter';

import {EXPAND_MS} from './taskbar-layout.js';

// Must match the taskbar's padding in modules style (stylesheet.css.in).
export const MODULE_MARGIN = 8;
export const MODULE_PADDING = 6;

const SHAPES = ['jeronix-fused', 'jeronix-flush-left', 'jeronix-flush-right', 'jeronix-floating'];

/** How a panel of width panelWidth meets a module expanded to width. */
export function shapeFor(side, width, panelWidth) {
    if (Math.abs(width - panelWidth) < 1)
        return 'jeronix-fused';
    if (side === 'left')
        return 'jeronix-flush-left';
    if (side === 'right')
        return 'jeronix-flush-right';
    return 'jeronix-floating';
}

/**
 * The actor drawing a menu's panel: GNOME's pointer actor around its
 * content. Usually menu.actor itself; GNOME's Quick Settings menu wraps it
 * in another actor (for its submenus), which has no size of its own.
 */
export function pointerOf(menu) {
    for (let a = menu.box; a; a = a.get_parent()) {
        if (a.has_style_class_name?.('popup-menu-boxpointer'))
            return a;
    }
    return menu.actor;
}

export class ModuleExpander {
    /**
     * @param {St.Widget} bar - the taskbar (the modules' container)
     * @param {TaskbarLayout} layout - its layout
     * @param {object} backdrops - {left, center, right} module backgrounds
     * @param {Function} onOpen - called with (side, open) when a panel
     *   opens (before it is placed) and when it closes
     */
    constructor(bar, layout, backdrops, onOpen = null) {
        this._bar = bar;
        this._layout = layout;
        this._backdrops = backdrops;
        this._onOpen = onOpen;
        this._attached = [];
        this._open = {};
    }

    /**
     * Shows menu as the expansion of the module on side. source is the
     * button a GNOME menu points at (null for menus placed with anchorFor).
     */
    attach(side, menu, source = null) {
        pointerOf(menu).add_style_class_name('jeronix-attached');
        const id = menu.connect('open-state-changed', (m, open) => {
            if (open)
                this._expand(side, menu, source);
            else
                this._collapse(side, menu, source);
        });
        this._attached.push({side, menu, id, source});
    }

    /**
     * The panel's width: as laid out once it is open, else as it asks to be
     * (some panels, like GNOME's Quick Settings menu, ask for no width at
     * all and are sized by their content as they open).
     */
    _panelWidth(menu) {
        const pointer = pointerOf(menu);
        const finite = v => Number.isFinite(v) && v > 0 ? v : 0;
        const allocated = pointer.has_allocation() && pointer.visible ? finite(pointer.width) : 0;
        return Math.max(allocated, finite(pointer.get_preferred_width(-1)[1]));
    }

    /**
     * Where a menu's panel stands, in stage coordinates: the module on side
     * expanded toward it ({x, y, width, height} of the module, panelWidth).
     */
    anchorFor(side, menu) {
        const panelWidth = this._panelWidth(menu);
        const rect = this._layout.targetRect(side, panelWidth);
        if (!rect)
            return null;
        const [bx, by] = this._bar.get_transformed_position();
        return {x: bx + rect[0], y: by + rect[1], width: rect[2], height: rect[3], panelWidth};
    }

    /** Whether a panel is open from the module on side. */
    isOpen(side) {
        return Boolean(this._open[side]);
    }

    _expand(side, menu, source) {
        this._open[side] = menu;
        this._onOpen?.(side, true);
        // Some panels fill in their content just after opening (the Control
        // Center), and some change size while open (modules switched on,
        // notifications arriving): the module follows the panel's width.
        const pointer = pointerOf(menu);
        pointer.connectObject(
            'notify::width', () => this._fit(side, menu, source),
            'notify::height', () => this._fit(side, menu, source),
            this);
        this._fit(side, menu, source);
        // The panel grows out of the module.
        const pivotX = {left: 0, center: 0.5, right: 1}[side];
        pointer.set_pivot_point(pivotX, 1);
        pointer.remove_transition('scale-y');
        pointer.scale_y = 0.94;
        pointer.ease({scale_y: 1, duration: EXPAND_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
    }

    /** Expands the module on side to the open panel's current width. */
    _fit(side, menu, source) {
        if (this._open[side] !== menu)
            return;
        const target = this.anchorFor(side, menu);
        if (!target || target.panelWidth < 1)
            return; // not measured yet: notify::width comes back
        this._layout.setExpanded(this._bar, side, target.panelWidth);
        const shape = shapeFor(side, target.width, target.panelWidth);
        const backdrop = this._backdrops[side];
        const pointer = pointerOf(menu);
        for (const actor of [backdrop, pointer]) {
            for (const other of SHAPES.filter(s => s !== shape))
                actor.remove_style_class_name(other);
            actor.add_style_class_name(shape);
        }
        backdrop.add_style_class_name('jeronix-module-open');
        // Stand on the module's top edge: GNOME opens a panel -arrow-rise
        // (MODULE_MARGIN) above the actor it points at. For our menus that
        // is the anchor, placed on the module's top just before opening
        // (not laid out yet, so not measured); GNOME's point at their
        // button (or the part of it their menu names as sourceActor).
        const pointsAt = source ? menu.sourceActor ?? source : null;
        const top = pointsAt ? pointsAt.get_transformed_position()[1] : target.y;
        // GNOME places a panel by its natural height; one capped shorter
        // (the notification center, by its maximum height) would end above
        // the module by the difference.
        const natural = pointer.get_preferred_size()[3];
        const shortfall = pointer.has_allocation() && Number.isFinite(natural) && Number.isFinite(pointer.height)
            ? Math.max(0, Math.round(natural - pointer.height)) : 0;
        const style = `-boxpointer-gap: ${Math.round(top - target.y) - MODULE_MARGIN - shortfall}px;`;
        if (pointer.get_style() !== style)
            pointer.set_style(style);
    }

    _collapse(side, menu, source) {
        if (this._open[side] !== menu)
            return;
        delete this._open[side];
        const pointer = pointerOf(menu);
        pointer.disconnectObject(this);
        this._layout.setExpanded(this._bar, side, 0);
        const backdrop = this._backdrops[side];
        backdrop.remove_style_class_name('jeronix-module-open');
        for (const shape of SHAPES) {
            backdrop.remove_style_class_name(shape);
            pointer.remove_style_class_name(shape);
        }
        pointer.set_style(null);
        pointer.remove_transition('scale-y');
        pointer.scale_y = 1;
        this._onOpen?.(side, false);
    }

    /** Which modules are expanded, how far, and where their panels are, for tests. */
    get state() {
        const panels = {};
        for (const [side, menu] of Object.entries(this._open)) {
            const box = menu.box; // the visible panel inside GNOME's pointer actor
            const [x, y] = box.get_transformed_position();
            const [w, h] = box.get_transformed_size();
            const pointer = pointerOf(menu);
            const [px, py] = pointer.get_transformed_position();
            const [pw, ph] = pointer.get_transformed_size();
            panels[side] = {rect: [x, y, w, h].map(Math.round), classes: pointer.get_style_class_name(),
                width: this._panelWidth(menu), pointerRect: [px, py, pw, ph].map(Math.round),
                gap: pointer.get_theme_node().get_length('-boxpointer-gap'),
                rise: pointer.get_theme_node().get_length('-arrow-rise')};
        }
        return {open: Object.keys(this._open), expansion: this._layout.expansion, panels};
    }

    destroy() {
        for (const {side, menu, id, source} of this._attached) {
            this._collapse(side, menu, source);
            menu.disconnect(id);
            pointerOf(menu).remove_style_class_name('jeronix-attached');
        }
        this._attached = [];
        this._layout.destroy();
    }
}
