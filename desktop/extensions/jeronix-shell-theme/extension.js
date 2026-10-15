// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Shell Theme: a stylesheet-only extension.
//
// GNOME Shell itself loads stylesheet-dark.css or stylesheet-light.css from
// this directory when the extension is enabled, swaps them when the color
// scheme changes and unloads them when it is disabled
// (js/ui/extensionSystem.js, _loadExtensionStylesheet). Those files are
// generated from the design tokens by scripts/jeronix_design.py; they are not
// in this source directory. No shell behavior is changed, so enable() and
// disable() have nothing to do.

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class JeronixShellThemeExtension extends Extension {
    enable() {
    }

    disable() {
    }
}
