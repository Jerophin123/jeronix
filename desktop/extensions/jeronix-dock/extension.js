// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Dock: a floating dock with favorites, running applications,
// window previews and configurable position and hiding. It does not touch
// Ubuntu's dock; layouts that use this dock switch Ubuntu's off explicitly
// and reversibly (see scripts/jeronix_layout.py).

import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Dock} from './dock.js';

export default class JeronixDockExtension extends Extension {
    enable() {
        if (this._settings) // repeated enable() from overlapping passes: no-op
            return;
        this._settings = this.getSettings();
        // A layout changes several keys at once; rebuild once, after the
        // burst, instead of once per key.
        this._settings.connectObject('changed', () => this._queueRebuild(), this);
        this._dock = new Dock(this._settings, this.path);
        Main.wm.addKeybinding('start-menu-shortcut', this._settings, Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this._dock?.toggleStartMenu());
    }

    _queueRebuild() {
        if (this._rebuildId)
            return;
        this._rebuildId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._rebuildId = 0;
            this._dock?.destroy();
            this._dock = new Dock(this._settings, this.path);
            return GLib.SOURCE_REMOVE;
        });
    }

    disable() {
        if (this._rebuildId) {
            GLib.source_remove(this._rebuildId);
            this._rebuildId = 0;
        }
        Main.wm.removeKeybinding('start-menu-shortcut');
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
