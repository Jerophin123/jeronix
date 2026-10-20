// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Quick Settings: adds a "Stay Awake" toggle that blocks screen
// blanking and automatic suspend while it is on, and gives JERONIX Settings
// the shell's screen brightness over D-Bus (brightness-service.js).
//
// The JERONIX Control Center (jeronix-dock) shows the same switch. It finds
// this extension through Main.extensionManager and uses the small public API
// at the end of the extension class (stayAwakeAvailable, stayAwakeActive,
// setStayAwake, watchStayAwake), so there is only ever one inhibitor.

import GObject from 'gi://GObject';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickToggle, SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {BrightnessService} from './brightness-service.js';
import {WifiIndicator} from './wifi-indicator.js';
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
        this._listeners = new Set();
    }

    get inhibitor() {
        return this._inhibitor;
    }

    addListener(callback) {
        this._listeners.add(callback);
    }

    removeListener(callback) {
        this._listeners.delete(callback);
    }

    _onInhibitorChanged(active, error) {
        this._toggle.sync();
        this._indicator.visible = active;
        for (const callback of this._listeners) {
            try {
                callback(active);
            } catch (e) {
                console.warn(`JERONIX Stay Awake listener: ${e.message}`);
            }
        }
        if (error) {
            console.warn(`JERONIX Stay Awake: ${error.message}`);
            Main.notifyError(_('Stay Awake failed'), error.message);
        }
    }

    destroy() {
        this._listeners.clear();
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
        const quickSettings = Main.panel.statusArea.quickSettings;
        quickSettings.addExternalIndicator(this._indicator);
        // Wi-Fi beside GNOME's network icon (which shows only the primary
        // connection): its signal whenever there is a Wi-Fi adapter.
        try {
            this._wifi = new WifiIndicator();
            quickSettings.addExternalIndicator(this._wifi);
            const network = quickSettings._network; // GNOME's network icon, if any
            if (network && network.get_parent() === this._wifi.get_parent())
                this._wifi.get_parent().set_child_above_sibling(this._wifi, network);
        } catch (e) { // the rest works without it (no NetworkManager)
            console.warn(`JERONIX Wi-Fi indicator: ${e.message}`);
            this._wifi?.destroy();
            this._wifi = null;
        }
        try {
            this._brightness = new BrightnessService();
        } catch (e) { // Stay Awake works without it
            console.warn(`JERONIX brightness service: ${e.message}`);
        }
    }

    disable() {
        this._brightness?.destroy();
        this._brightness = null;
        this._wifi?.destroy();
        this._wifi = null;
        this._indicator?.destroy();
        this._indicator = null;
    }

    // -- public API for the JERONIX Control Center ---------------------------

    get stayAwakeAvailable() {
        return Boolean(this._indicator);
    }

    /** Whether idle and suspend are currently blocked. */
    get stayAwakeActive() {
        return Boolean(this._indicator?.inhibitor.active);
    }

    /** Whether Stay Awake has been asked for (it may still be starting). */
    get stayAwakeWanted() {
        return Boolean(this._indicator?.inhibitor.wanted);
    }

    setStayAwake(on) {
        const inhibitor = this._indicator?.inhibitor;
        if (!inhibitor)
            return;
        if (on)
            inhibitor.enable();
        else
            inhibitor.disable();
    }

    /**
     * Calls callback(active) whenever the state changes, until the returned
     * function is called (or this extension is disabled).
     */
    /** Read-only state for tests (tests/integration/desktop_lifecycle.py). */
    debugState() {
        return {wifi: this._wifi?.debugState() ?? null};
    }

    watchStayAwake(callback) {
        const indicator = this._indicator;
        if (!indicator)
            return () => {};
        indicator.addListener(callback);
        return () => indicator.removeListener(callback);
    }
}
