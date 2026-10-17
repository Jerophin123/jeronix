// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Dock: a floating dock with favorites, running applications,
// window previews and configurable position and hiding. It does not touch
// Ubuntu's dock; layouts that use this dock switch Ubuntu's off explicitly
// and reversibly (see scripts/jeronix_layout.py).

import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Dock} from './dock.js';

// GNOME's own modes for the Super key (js/ui/main.js).
const OVERLAY_MODES = Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW;

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
        this._takeSuperKey();
    }

    // Super opens the Start menu, as in Windows. GNOME toggles the overview
    // from its own 'overlay-key' handler; that handler is blocked (not
    // removed) while the extension is enabled and unblocked on disable.
    // GNOME only emits 'overlay-key' on the desktop and in the overview.
    _takeSuperKey() {
        const handler = GObject.signal_handler_find(global.display, {signalId: 'overlay-key'});
        if (handler) {
            GObject.signal_handler_block(global.display, handler);
            this._blockedOverlayHandler = handler;
        }
        this._overlayKeyId = global.display.connect('overlay-key', () => {
            if (!this._dock || !this._settings.get_boolean('super-key-start-menu')) {
                if (Main.actionMode !== Shell.ActionMode.POPUP)
                    Main.overview.toggle();
            } else if (this._dock.startMenuOpen || Main.actionMode !== Shell.ActionMode.POPUP) {
                // Toggles: Super also closes the Start menu. Ignored while
                // another menu (Quick Settings, calendar...) is open.
                this._dock.toggleStartMenu();
            }
        });
        // GNOME allows Super only on the desktop and in the overview; allow
        // it while a menu is open too, so Super can close the Start menu.
        Main.wm.allowKeybinding('overlay-key', OVERLAY_MODES | Shell.ActionMode.POPUP);
    }

    _releaseSuperKey() {
        Main.wm.allowKeybinding('overlay-key', OVERLAY_MODES);
        if (this._overlayKeyId)
            global.display.disconnect(this._overlayKeyId);
        this._overlayKeyId = 0;
        if (this._blockedOverlayHandler)
            GObject.signal_handler_unblock(global.display, this._blockedOverlayHandler);
        this._blockedOverlayHandler = 0;
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
        this._releaseSuperKey();
        Main.wm.removeKeybinding('start-menu-shortcut');
        this._settings.disconnectObject(this);
        this._dock?.destroy();
        this._dock = null;
        this._settings = null;
    }

    // Read-only state for tests (tests/integration/desktop_lifecycle.py).
    debugState() {
        const state = this._dock?.debugState() ?? null;
        if (state)
            state.superKeyTaken = Boolean(this._overlayKeyId && this._blockedOverlayHandler);
        return state;
    }
}
