// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Quick Settings: adds a "Stay Awake" toggle that blocks screen
// blanking and automatic suspend while it is on.

import GObject from 'gi://GObject';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Inhibitor, InhibitFlags, createSessionManagerClient} from './inhibitor.js';

const ICON_NAME = 'view-reveal-symbolic';

const StayAwakeToggle = GObject.registerClass(
class StayAwakeToggle extends QuickToggle {
    constructor(inhibitor) {
        super({
            title: _('Stay Awake'),
            iconName: ICON_NAME,
            // The checked state follows the real inhibitor state, not clicks.
            toggleMode: false,
        });
        this._inhibitor = inhibitor;
        this.connect('clicked', () => {
            if (this._inhibitor.wanted)
                this._inhibitor.disable();
            else
                this._inhibitor.enable();
        });
    }

    sync() {
        const active = this._inhibitor.active;
        this.checked = active;
        this.subtitle = active ? _('Screen and suspend blocked') : null;
    }
});

const StayAwakeIndicator = GObject.registerClass(
class StayAwakeIndicator extends SystemIndicator {
    constructor(appId) {
        super();

        this._inhibitor = new Inhibitor(createSessionManagerClient(), {
            appId,
            reason: _('Stay Awake is on in Quick Settings'),
            flags: InhibitFlags.IDLE | InhibitFlags.SUSPEND,
            onChanged: (active, error) => this._onInhibitorChanged(active, error),
        });

        this._indicator = this._addIndicator();
        this._indicator.icon_name = ICON_NAME;
        this._indicator.visible = false;

        this._toggle = new StayAwakeToggle(this._inhibitor);
        this.quickSettingsItems.push(this._toggle);
    }

    _onInhibitorChanged(active, error) {
        this._toggle.sync();
        this._indicator.visible = active;
        if (error) {
            console.warn(`JERONIX Stay Awake: ${error.message}`);
            Main.notifyError(_('Stay Awake failed'), error.message);
        }
    }

    destroy() {
        this._inhibitor.destroy();
        this._inhibitor = null;
        this.quickSettingsItems.forEach(item => item.destroy());
        this.quickSettingsItems.length = 0;
        super.destroy();
    }
});

export default class JeronixQuickSettingsExtension extends Extension {
    enable() {
        // GNOME 50 can call enable() twice in a row (overlapping async
        // passes in extensionSystem.js); never add a second toggle.
        if (this._indicator)
            return;
        this._indicator = new StayAwakeIndicator(this.uuid);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
