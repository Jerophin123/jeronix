// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Shell Theme: the JERONIX stylesheet, and the JERONIX lock screen.
//
// GNOME Shell itself loads stylesheet-dark.css or stylesheet-light.css from
// this directory when the extension is enabled, swaps them when the color
// scheme changes and unloads them when it is disabled
// (js/ui/extensionSystem.js, _loadExtensionStylesheet). Those files are
// generated from the design tokens by scripts/jeronix_design.py; they are not
// in this source directory.
//
// The extension stays enabled while the screen is locked (session-modes in
// metadata.json), where lockscreen.js replaces GNOME's lock screen look.

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {LockScreen} from './lockscreen.js';

export default class JeronixShellThemeExtension extends Extension {
    enable() {
        if (this._lockScreen) // repeated enable() from overlapping passes: no-op
            return;
        this._lockScreen = new LockScreen();
    }

    disable() {
        this._lockScreen?.destroy();
        this._lockScreen = null;
    }

    // Read-only state for tests (tests/integration/desktop_lifecycle.py).
    debugState() {
        return this._lockScreen?.debugState() ?? null;
    }
}
