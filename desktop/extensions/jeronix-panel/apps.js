// SPDX-License-Identifier: GPL-3.0-or-later
//
// Desktop file IDs of the JERONIX applications and a launcher that reports
// a missing application instead of failing silently.

import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

export const JERONIX_APPS = Object.freeze({
    launcher: 'io.jeronix.Launcher.desktop',
    layoutStudio: 'io.jeronix.LayoutStudio.desktop',
    settings: 'io.jeronix.Settings.desktop',
    systemInfo: 'io.jeronix.SystemInfo.desktop',
    welcome: 'io.jeronix.Welcome.desktop',
});

export function launchApp(desktopId) {
    const app = Shell.AppSystem.get_default().lookup_app(desktopId);
    if (!app) {
        Main.notify(_('Application not installed'), desktopId);
        return false;
    }
    Main.overview.hide();
    app.activate();
    return true;
}
