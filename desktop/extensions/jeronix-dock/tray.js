// SPDX-License-Identifier: GPL-3.0-or-later
//
// Windows 11-style system tray: GNOME's own Quick Settings (network,
// sound, power, Stay Awake, ...) and the clock with the notification center
// and calendar are moved from the top bar into the taskbar, with their menus
// opening upward. They are the real GNOME components, so every control keeps
// working; on disable they go back exactly where they were.

import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Order in the tray, left to right (as in Windows 11: status, then clock).
const ROLES = ['quickSettings', 'dateMenu'];

function setArrowSide(menu, side) {
    const pointer = menu?._boxPointer;
    if (pointer) {
        pointer._arrowSide = side;
        pointer._userArrowSide = side;
    }
}

export class Tray {
    constructor(box, side = St.Side.BOTTOM) {
        this._box = box;
        this._moved = [];
        for (const role of ROLES) {
            const indicator = Main.panel.statusArea[role];
            const container = indicator?.container;
            if (!container)
                continue;
            const parent = container.get_parent();
            const index = parent ? parent.get_children().indexOf(container) : -1;
            parent?.remove_child(container);
            box.add_child(container);
            indicator.add_style_class_name('jeronix-tray-button');
            setArrowSide(indicator.menu, side);
            this._moved.push({role, indicator, container, parent, index});
        }
    }

    get roles() {
        return this._moved.map(m => m.role);
    }

    restore() {
        for (const {indicator, container, parent, index} of [...this._moved].reverse()) {
            indicator.menu?.close?.();
            container.get_parent()?.remove_child(container);
            if (parent)
                parent.insert_child_at_index(container, Math.max(0, index));
            indicator.remove_style_class_name('jeronix-tray-button');
            setArrowSide(indicator.menu, St.Side.TOP);
        }
        this._moved = [];
    }
}

// Hides GNOME's top bar while the taskbar carries its contents. The panel
// box collapses to zero height, so it reserves no space; showing the panel
// again restores it. The overview, lock screen and login screen are not
// affected (the extension is disabled outside the user session).
export class TopBar {
    constructor() {
        this._hidden = false;
    }

    hide() {
        if (this._hidden)
            return;
        Main.panel.hide();
        this._hidden = true;
    }

    restore() {
        if (!this._hidden)
            return;
        Main.panel.show();
        this._hidden = false;
    }

    get hidden() {
        return this._hidden;
    }
}
