// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Dock: a floating dock with favorites, running applications,
// window previews and configurable position and hiding. It does not touch
// Ubuntu's dock; layouts that use this dock switch Ubuntu's off explicitly
// and reversibly (see scripts/jeronix_layout.py).

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Dock} from './dock.js';

export default class JeronixDockExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        // Settings change rarely; rebuilding keeps every code path simple.
        this._settings.connectObject('changed', () => this._rebuild(), this);
        this._dock = new Dock(this._settings);
    }

    _rebuild() {
        this._dock?.destroy();
        this._dock = new Dock(this._settings);
    }

    disable() {
        this._settings.disconnectObject(this);
        this._dock?.destroy();
        this._dock = null;
        this._settings = null;
    }

    // Read-only state for tests (tests/integration/desktop_lifecycle.py).
    debugState() {
        return this._dock?.debugState() ?? null;
    }
}
