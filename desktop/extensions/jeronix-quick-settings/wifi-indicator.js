// SPDX-License-Identifier: GPL-3.0-or-later
//
// Wi-Fi in the status icons, always. GNOME shows one network icon, for the
// primary connection: with a cable plugged in, a Wi-Fi adapter gets no icon
// at all, connected or not, and its signal is nowhere to be seen. As on
// Windows, this shows Wi-Fi beside it whenever the computer has a Wi-Fi
// adapter: its signal strength while connected (as GNOME draws it), a
// searching icon while connecting, and Wi-Fi off otherwise. Where Wi-Fi is
// the primary connection GNOME's own icon already shows it, so this one
// steps aside. The menu stays GNOME's (the Wi-Fi toggle in Quick Settings).

import GObject from 'gi://GObject';
import NM from 'gi://NM';

import {SystemIndicator} from 'resource:///org/gnome/shell/ui/quickSettings.js';

import {wifiIcon} from './wifi-model.js';

export const WifiIndicator = GObject.registerClass(
class JeronixWifiIndicator extends SystemIndicator {
    _init() {
        super._init();
        this._icon = this._addIndicator();
        this._icon.visible = false;
        this._client = null;
        NM.Client.new_async(null, (o, res) => {
            try {
                this._client = NM.Client.new_finish(res);
            } catch (e) {
                console.warn(`JERONIX Wi-Fi indicator: ${e.message}`);
                return;
            }
            if (this._destroyed)
                return;
            this._client.connectObject(
                'device-added', () => this._watchDevices(),
                'device-removed', () => this._watchDevices(),
                'notify::wireless-enabled', () => this._sync(),
                'notify::primary-connection', () => this._sync(), this);
            this._watchDevices();
        });
    }

    /** The first Wi-Fi adapter (a computer rarely has two). */
    _wifiDevice() {
        return (this._client?.get_devices() ?? []).find(d => d.get_device_type() === NM.DeviceType.WIFI) ?? null;
    }

    _watchDevices() {
        const device = this._wifiDevice();
        if (device !== this._device) {
            this._device?.disconnectObject(this);
            this._device = device;
            device?.connectObject(
                'state-changed', () => this._sync(),
                'notify::active-access-point', () => this._watchAccessPoint(), this);
        }
        this._watchAccessPoint();
    }

    _watchAccessPoint() {
        const ap = this._device?.get_active_access_point() ?? null;
        if (ap !== this._ap) {
            this._ap?.disconnectObject(this);
            this._ap = ap;
            ap?.connectObject('notify::strength', () => this._sync(), this);
        }
        this._sync();
    }

    _sync() {
        if (this._destroyed)
            return;
        const device = this._device;
        const primary = this._client?.get_primary_connection();
        const {icon, visible} = wifiIcon(device ? {state: device.get_state(), strength: this._ap?.get_strength()}
            : null, {
            radioOn: this._client?.wireless_enabled ?? true,
            primaryIsWifi: Boolean(primary && primary.get_devices().includes(device)),
        });
        if (icon)
            this._icon.icon_name = icon;
        this._icon.visible = visible;
    }

    /** For tests: what the icon shows. */
    debugState() {
        return {visible: this._icon.visible, icon: this._icon.icon_name ?? null,
            device: this._device?.get_iface() ?? null};
    }

    destroy() {
        this._destroyed = true;
        this._client?.disconnectObject(this);
        this._device?.disconnectObject(this);
        this._ap?.disconnectObject(this);
        this._client = this._device = this._ap = null;
        super.destroy();
    }
});
