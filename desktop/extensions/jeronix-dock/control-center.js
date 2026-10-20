// SPDX-License-Identifier: GPL-3.0-or-later
//
// The JERONIX Control Center, in the style of macOS: rounded modules on a
// 4-column grid. Wi-Fi, Bluetooth, Airplane Mode and VPN share one card;
// beside them Do Not Disturb, Stay Awake, Dark Mode, Night Light and Power
// Mode; then Display and Sound sliders, Now Playing, Battery, Screenshot,
// Screen Recording and Settings. Wi-Fi, Bluetooth, VPN, Sound and Power
// Mode open a list in place (networks, devices, outputs, modes).
//
// It replaces the content of GNOME's Quick Settings menu, so every way of
// opening that menu (the tray's status icons, Super+S, moving between tray
// menus) opens the Control Center; GNOME's grid is hidden for as long as
// the extension runs and is never shown.
//
// Which modules appear, and in what order, is the 'control-center-modules'
// setting (JERONIX Settings → Control Center); a module whose hardware or
// service is missing is left out, and the rest are packed without holes
// (cc-model.js). The content scrolls when the screen is short.
//
// Every module uses a stable interface: libnm, gsd-rfkill, BlueZ, UPower,
// power-profiles-daemon and MPRIS over D-Bus, GSettings, and the shell's
// own mixer, brightness manager and screenshot UI.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gvc from 'gi://Gvc';
import NM from 'gi://NM';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Screenshot from 'resource:///org/gnome/shell/ui/screenshot.js';
import * as Slider from 'resource:///org/gnome/shell/ui/slider.js';
import * as Util from 'resource:///org/gnome/shell/misc/util.js';
import * as Volume from 'resource:///org/gnome/shell/ui/status/volume.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {COLUMNS, blocks, duration, needsPassword, networks, pack, signalIcon} from './cc-model.js';

const SETTINGS_APP = 'io.jeronix.Settings.desktop';
const STAY_AWAKE_UUID = 'jeronix-quick-settings@jeronix';
const MODULES_KEY = 'control-center-modules';
const SOLID_KEY = 'control-center-reduce-transparency';
const RFKILL = ['org.gnome.SettingsDaemon.Rfkill', '/org/gnome/SettingsDaemon/Rfkill',
    'org.gnome.SettingsDaemon.Rfkill'];
const POWER_PROFILES = [
    ['org.freedesktop.UPower.PowerProfiles', '/org/freedesktop/UPower/PowerProfiles',
        'org.freedesktop.UPower.PowerProfiles'],
    ['net.hadess.PowerProfiles', '/net/hadess/PowerProfiles', 'net.hadess.PowerProfiles'],
];
const BATTERY = ['org.freedesktop.UPower', '/org/freedesktop/UPower/devices/DisplayDevice',
    'org.freedesktop.UPower.Device'];
// Whether the displays can show Night Light (most virtual machines can't).
const DISPLAY_CONFIG = ['org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
    'org.gnome.Mutter.DisplayConfig'];
const MPRIS_PREFIX = 'org.mpris.MediaPlayer2.';
const MPRIS_PLAYER = 'org.mpris.MediaPlayer2.Player';
// Gvc numbers output devices from 1; probing this many finds the outputs
// that existed before the Control Center was created.
const MAX_OUTPUT_ID = 1024;
// Space kept free above and below the menu when it fits the screen.
const MARGIN = 72;
const DETAIL_KINDS = ['wifi', 'bluetooth', 'vpn', 'sound', 'power-mode'];

function warn(what, error) {
    console.warn(`JERONIX Control Center: ${what}: ${error?.message ?? error}`);
}

/** Gio.Settings for schemaId if it is installed and has every key, else null. */
function optionalSettings(schemaId, ...keys) {
    const schema = Gio.SettingsSchemaSource.get_default()?.lookup(schemaId, true);
    if (!schema || !keys.every(k => schema.has_key(k)))
        return null;
    return new Gio.Settings({settings_schema: schema});
}

/** Opens JERONIX Settings, on a page if given (settings.py --page NAME). */
export function openSettings(page = null) {
    const app = Shell.AppSystem.get_default().lookup_app(SETTINGS_APP);
    const info = app?.get_app_info();
    if (!info)
        return;
    if (!page) {
        app.activate();
        return;
    }
    try {
        const [, argv] = GLib.shell_parse_argv(info.get_commandline());
        // Drop field codes (%U, %f...); the template has none, but be safe.
        Util.spawn([...argv.filter(a => !/^%[a-zA-Z]$/.test(a)), '--page', page]);
    } catch (e) {
        warn('cannot open Settings', e);
        app.activate();
    }
}

// -- building blocks ---------------------------------------------------------------

/** Shows a theme icon name or a Gio.Icon in an St.Icon. */
function setIcon(icon, spec) {
    if (typeof spec === 'string') {
        icon.gicon = null;
        icon.icon_name = spec;
    } else {
        icon.gicon = spec;
    }
}

function makeIcon(spec, styleClass) {
    const icon = new St.Icon({style_class: styleClass});
    setIcon(icon, spec);
    return icon;
}

function card(extraClass = '', vertical = true) {
    return new St.BoxLayout({
        style_class: `jeronix-cc-module ${extraClass}`.trim(),
        orientation: vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL,
        x_expand: true,
        y_expand: true,
    });
}

function label(text, styleClass) {
    const l = new St.Label({text, style_class: styleClass, y_align: Clutter.ActorAlign.CENTER});
    l.clutter_text.ellipsize = 3; // Pango.EllipsizeMode.END
    return l;
}

function setChecked(actor, checked) {
    if (checked)
        actor.add_style_pseudo_class('checked');
    else
        actor.remove_style_pseudo_class('checked');
}

/**
 * A round toggle (macOS: the filled circle) with a title and status beside
 * it. onToggle runs when the circle is clicked; onOpen, if given, when the
 * text is clicked (with a chevron when it opens a list in place).
 */
class ToggleRow {
    constructor(iconSpec, title, onToggle, onOpen = null, chevron = false) {
        this.actor = new St.BoxLayout({style_class: 'jeronix-cc-row', x_expand: true});
        this._icon = makeIcon(iconSpec, 'jeronix-cc-circle-icon');
        this.circle = new St.Button({
            style_class: 'jeronix-cc-circle', can_focus: true, accessible_name: title,
            y_align: Clutter.ActorAlign.CENTER, child: this._icon,
        });
        this.circle.connect('clicked', () => onToggle());
        this.actor.add_child(this.circle);
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, y_align: Clutter.ActorAlign.CENTER,
            x_expand: true});
        this._title = label(title, 'jeronix-cc-row-title');
        this._status = label('', 'jeronix-cc-row-status');
        text.add_child(this._title);
        text.add_child(this._status);
        if (onOpen) {
            const box = new St.BoxLayout({x_expand: true});
            box.add_child(text);
            if (chevron) {
                box.add_child(new St.Icon({icon_name: 'go-next-symbolic', style_class: 'jeronix-cc-chevron',
                    y_align: Clutter.ActorAlign.CENTER}));
            }
            const open = new St.Button({style_class: 'jeronix-cc-row-text', can_focus: true, x_expand: true,
                accessible_name: `${title}: ${_('more')}`, child: box});
            open.connect('clicked', () => onOpen());
            this.actor.add_child(open);
        } else {
            this.actor.add_child(text);
        }
    }

    setTitle(title) {
        this._title.text = title;
        this.circle.accessible_name = title;
    }

    set(active, status, iconSpec = null) {
        this.circle.checked = active;
        this._status.text = status;
        if (iconSpec)
            setIcon(this._icon, iconSpec);
    }

    set sensitive(value) {
        this.circle.reactive = value;
    }

    get state() {
        return {active: this.circle.checked, status: this._status.text, title: this._title.text};
    }
}

/** A square module: a round icon over a label (Dark Mode, Screenshot...). */
class Tile {
    constructor(iconSpec, title, onClick, toggles = false) {
        this.actor = new St.Button({
            style_class: `jeronix-cc-module jeronix-cc-tile${toggles ? ' jeronix-cc-tile-toggle' : ''}`,
            can_focus: true, x_expand: true, y_expand: true, accessible_name: title,
        });
        const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
            y_align: Clutter.ActorAlign.CENTER, style_class: 'jeronix-cc-tile-box'});
        this._circle = new St.Bin({style_class: 'jeronix-cc-circle', x_align: Clutter.ActorAlign.CENTER,
            child: makeIcon(iconSpec, 'jeronix-cc-tile-icon')});
        box.add_child(this._circle);
        // Narrow tiles: wrap a long label onto a second line instead of
        // cutting it off.
        const text = new St.Label({text: title, style_class: 'jeronix-cc-tile-label',
            x_align: Clutter.ActorAlign.CENTER});
        text.clutter_text.line_wrap = true;
        text.clutter_text.ellipsize = 0; // Pango.EllipsizeMode.NONE
        box.add_child(text);
        this.actor.set_child(box);
        this.actor.connect('clicked', () => onClick());
        this._toggles = toggles;
    }

    set(active) {
        this.actor.checked = active;
        setChecked(this._circle, this._toggles && active);
    }

    get state() {
        return {active: this.actor.checked};
    }
}

/** A titled slider module (Display, Sound), with an optional list button. */
class SliderModule {
    constructor(title, iconName, {onIconClicked = null, onOpen = null} = {}) {
        this.actor = card('jeronix-cc-slider-module');
        this.actor.add_child(label(title, 'jeronix-cc-module-title'));
        const row = new St.BoxLayout({style_class: 'jeronix-cc-slider-row', x_expand: true});
        this.icon = new St.Icon({icon_name: iconName, style_class: 'jeronix-cc-slider-icon'});
        if (onIconClicked) {
            const button = new St.Button({style_class: 'jeronix-cc-slider-button', can_focus: true,
                accessible_name: _('Mute'), child: this.icon, y_align: Clutter.ActorAlign.CENTER});
            button.connect('clicked', () => onIconClicked());
            row.add_child(button);
        } else {
            this.icon.y_align = Clutter.ActorAlign.CENTER;
            row.add_child(this.icon);
        }
        this.slider = new Slider.Slider(0);
        this.slider.x_expand = true;
        this.slider.y_align = Clutter.ActorAlign.CENTER;
        this.slider.accessible_name = title;
        row.add_child(this.slider);
        this.openButton = null;
        if (onOpen) {
            this.openButton = new St.Button({style_class: 'jeronix-cc-slider-button', can_focus: true,
                accessible_name: `${title}: ${_('devices')}`, y_align: Clutter.ActorAlign.CENTER,
                child: new St.Icon({icon_name: 'go-next-symbolic', style_class: 'jeronix-cc-slider-icon'})});
            this.openButton.connect('clicked', () => onOpen());
            row.add_child(this.openButton);
        }
        this.actor.add_child(row);
    }
}

// -- services ------------------------------------------------------------------------

/** A D-Bus proxy created asynchronously, with property helpers. */
class DBusClient {
    constructor(bus, [name, path, iface], onChanged, flags = Gio.DBusProxyFlags.NONE) {
        this._iface = iface;
        this._onChanged = onChanged;
        this.proxy = null;
        Gio.DBusProxy.new_for_bus(bus, flags, null, name, path, iface, null, (obj, res) => {
            try {
                const proxy = Gio.DBusProxy.new_for_bus_finish(res);
                if (this._destroyed)
                    return;
                this.proxy = proxy;
                proxy.connectObject(
                    'g-properties-changed', () => this._onChanged(),
                    'notify::g-name-owner', () => this._onChanged(),
                    this);
            } catch (e) {
                warn(`${name} unavailable`, e);
            }
            if (!this._destroyed)
                this._onChanged();
        });
    }

    get owned() {
        return Boolean(this.proxy?.g_name_owner);
    }

    get(property) {
        return this.owned ? this.proxy.get_cached_property(property)?.recursiveUnpack() : undefined;
    }

    set(property, variant) {
        this.proxy?.call('org.freedesktop.DBus.Properties.Set',
            new GLib.Variant('(ssv)', [this._iface, property, variant]),
            Gio.DBusCallFlags.NONE, -1, null, (proxy, res) => {
                try {
                    proxy.call_finish(res);
                } catch (e) {
                    warn(`cannot set ${property}`, e);
                }
            });
    }

    call(method) {
        this.proxy?.call(method, null, Gio.DBusCallFlags.NONE, -1, null, (proxy, res) => {
            try {
                proxy.call_finish(res);
            } catch (e) {
                warn(`${method} failed`, e);
            }
        });
    }

    destroy() {
        this._destroyed = true;
        this.proxy?.disconnectObject(this);
        this.proxy = null;
    }
}

function ssidText(bytes) {
    const data = bytes?.get_data();
    return data && data.length ? NM.utils_ssid_to_utf8(data) : null;
}

/** NetworkManager: Wi-Fi, the wired state, saved VPNs. */
class NetworkService {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this.client = null;
        this._device = null;
        NM.Client.new_async(null, (obj, res) => {
            try {
                const client = NM.Client.new_finish(res);
                if (this._destroyed)
                    return;
                this.client = client;
                client.connectObject(
                    'notify::wireless-enabled', () => this._changed(),
                    'notify::wireless-hardware-enabled', () => this._changed(),
                    'notify::active-connections', () => this._changed(),
                    'notify::primary-connection', () => this._changed(),
                    'device-added', () => this._changed(),
                    'device-removed', () => this._changed(),
                    'connection-added', () => this._changed(),
                    'connection-removed', () => this._changed(),
                    this);
            } catch (e) {
                warn('NetworkManager unavailable', e);
            }
            this._changed();
        });
    }

    _changed() {
        if (this._destroyed)
            return;
        const device = this.wifiDevice;
        if (device !== this._device) {
            this._device?.disconnectObject(this);
            this._device = device;
            device?.connectObject(
                'access-point-added', () => this._onChanged(),
                'access-point-removed', () => this._onChanged(),
                'state-changed', () => this._onChanged(),
                this);
        }
        this._onChanged();
    }

    get available() {
        return Boolean(this.client?.get_nm_running());
    }

    get wifiDevice() {
        return this.client?.get_devices().find(d => d.get_device_type() === NM.DeviceType.WIFI) ?? null;
    }

    get wifiEnabled() {
        return Boolean(this.client?.wireless_enabled);
    }

    get wifiBlocked() {
        return this.client ? !this.client.wireless_hardware_enabled : true;
    }

    _active(type) {
        return this.client?.get_active_connections().find(c => c.get_connection_type() === type) ?? null;
    }

    get wifiName() {
        return ssidText(this.wifiDevice?.get_active_access_point()?.get_ssid() ?? null) ??
            this._active('802-11-wireless')?.get_id() ?? null;
    }

    get wiredConnected() {
        return Boolean(this._active('802-3-ethernet'));
    }

    setWifiEnabled(enabled) {
        this.client?.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, 'WirelessEnabled',
            GLib.Variant.new_boolean(enabled), -1, null, (client, res) => {
                try {
                    client.dbus_set_property_finish(res);
                } catch (e) {
                    warn('cannot switch Wi-Fi', e);
                }
            });
    }

    requestScan() {
        this.wifiDevice?.request_scan_async(null, (device, res) => {
            try {
                device.request_scan_finish(res);
            } catch {
                // Scanning again too soon is refused; the last results stay.
            }
        });
    }

    /** Visible networks: [{ssid, strength, secure, active, saved, ap}]. */
    networks() {
        const device = this.wifiDevice;
        if (!device)
            return [];
        const activeSsid = ssidText(device.get_active_access_point()?.get_ssid() ?? null);
        const points = device.get_access_points().map(ap => ({
            ssid: ssidText(ap.get_ssid()),
            strength: ap.get_strength(),
            secure: needsPassword(ap.get_flags(), ap.get_wpa_flags(), ap.get_rsn_flags()),
            ap,
        }));
        return networks(points).map(n => ({...n, active: n.ssid === activeSsid, saved: Boolean(this.saved(n.ssid))}));
    }

    saved(ssid) {
        return this.client?.get_connections()
            .find(c => ssidText(c.get_setting_wireless()?.get_ssid() ?? null) === ssid) ?? null;
    }

    /** Joins a network; returns false when it needs a password (asked in Settings). */
    join(network) {
        const device = this.wifiDevice;
        const saved = this.saved(network.ssid);
        if (saved) {
            this.client.activate_connection_async(saved, device, null, null, (client, res) => {
                try {
                    client.activate_connection_finish(res);
                } catch (e) {
                    warn(`cannot join ${network.ssid}`, e);
                }
            });
            return true;
        }
        if (network.secure)
            return false;
        this.client.add_and_activate_connection_async(null, device, network.ap.get_path(), null, (client, res) => {
            try {
                client.add_and_activate_connection_finish(res);
            } catch (e) {
                warn(`cannot join ${network.ssid}`, e);
            }
        });
        return true;
    }

    /** Saved VPN and WireGuard connections: [{connection, name, active}]. */
    vpns() {
        if (!this.client)
            return [];
        const activeByUuid = new Map(this.client.get_active_connections().map(a => [a.get_uuid(), a]));
        return this.client.get_connections()
            .filter(c => ['vpn', 'wireguard'].includes(c.get_connection_type()))
            .map(c => ({connection: c, name: c.get_id(), active: activeByUuid.get(c.get_uuid()) ?? null}))
            .sort((a, b) => a.name.localeCompare(b.name));
    }

    toggleVpn(vpn) {
        if (vpn.active) {
            this.client.deactivate_connection_async(vpn.active, null, (client, res) => {
                try {
                    client.deactivate_connection_finish(res);
                } catch (e) {
                    warn(`cannot disconnect ${vpn.name}`, e);
                }
            });
        } else {
            this.client.activate_connection_async(vpn.connection, null, null, null, (client, res) => {
                try {
                    client.activate_connection_finish(res);
                } catch (e) {
                    warn(`cannot connect ${vpn.name}`, e);
                }
            });
        }
    }

    destroy() {
        this._destroyed = true;
        this._device?.disconnectObject(this);
        this._device = null;
        this.client?.disconnectObject(this);
        this.client = null;
    }
}

/** Paired Bluetooth devices from BlueZ (system bus). */
class BluetoothService {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this.devices = [];
        this._busy = new Set();
    }

    refresh() {
        Gio.DBus.system.call('org.bluez', '/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects', null,
            new GLib.VariantType('(a{oa{sa{sv}}})'), Gio.DBusCallFlags.NONE, 5000, null, (bus, res) => {
                if (this._destroyed)
                    return;
                let objects = {};
                try {
                    [objects] = bus.call_finish(res).recursiveUnpack();
                } catch {
                    // No BlueZ, or no adapter: no devices.
                }
                this.devices = Object.entries(objects)
                    .filter(([, ifaces]) => ifaces['org.bluez.Device1']?.Paired)
                    .map(([path, ifaces]) => {
                        const d = ifaces['org.bluez.Device1'];
                        return {path, name: d.Alias || d.Name || d.Address || _('Device'),
                            icon: `${d.Icon || 'bluetooth-active'}-symbolic`, connected: Boolean(d.Connected)};
                    })
                    .sort((a, b) => b.connected - a.connected || a.name.localeCompare(b.name));
                this._onChanged();
            });
    }

    isBusy(device) {
        return this._busy.has(device.path);
    }

    toggle(device) {
        if (this._busy.has(device.path))
            return;
        this._busy.add(device.path);
        this._onChanged();
        Gio.DBus.system.call('org.bluez', device.path, 'org.bluez.Device1',
            device.connected ? 'Disconnect' : 'Connect', null, null, Gio.DBusCallFlags.NONE, 30000, null,
            (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch (e) {
                    warn(`Bluetooth ${device.name}`, e);
                }
                if (this._destroyed)
                    return;
                this._busy.delete(device.path);
                this.refresh();
            });
    }

    destroy() {
        this._destroyed = true;
    }
}

/** The default output: volume, mute, and the output devices to choose from. */
class SoundService {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._control = Volume.getMixerControl();
        this._outputs = new Set();
        this._activeOutput = null;
        this._control.connectObject(
            'state-changed', () => this._sync(),
            'default-sink-changed', () => this._sync(),
            'stream-removed', () => this._sync(),
            'output-added', (c, id) => {
                this._outputs.add(id);
                this._onChanged();
            },
            'output-removed', (c, id) => {
                this._outputs.delete(id);
                this._onChanged();
            },
            'active-output-update', (c, id) => {
                this._activeOutput = id;
                this._onChanged();
            },
            this);
        this._sync();
    }

    _sync() {
        if (!this._probed && this._control.get_state() === Gvc.MixerControlState.READY) {
            // Outputs added before this service existed.
            for (let id = 1; id <= MAX_OUTPUT_ID; id++) {
                if (this._control.lookup_output_id(id))
                    this._outputs.add(id);
            }
            this._probed = true;
        }
        const stream = this._control.get_default_sink();
        if (stream !== this._stream) {
            this._stream?.disconnectObject(this);
            this._stream = stream;
            stream?.connectObject(
                'notify::volume', () => this._onChanged(),
                'notify::is-muted', () => this._onChanged(),
                'notify::port', () => this._syncActive(),
                this);
        }
        this._syncActive();
    }

    _syncActive() {
        const device = this._stream ? this._control.lookup_device_from_stream(this._stream) : null;
        if (device)
            this._activeOutput = device.get_id();
        this._onChanged();
    }

    get available() {
        return Boolean(this._stream);
    }

    get muted() {
        return Boolean(this._stream?.is_muted);
    }

    /** 0..1 of the normal maximum. */
    get level() {
        if (!this._stream)
            return 0;
        return this.muted ? 0 : Math.min(1, this._stream.volume / this._control.get_vol_max_norm());
    }

    // Same rules as GNOME's own volume slider (js/ui/status/volume.js).
    setLevel(value) {
        const stream = this._stream;
        if (!stream)
            return;
        const volume = value * this._control.get_vol_max_norm();
        const wasMuted = stream.is_muted;
        if (volume < 1) {
            stream.volume = 0;
            if (!wasMuted)
                stream.change_is_muted(true);
        } else {
            stream.volume = volume;
            if (wasMuted)
                stream.change_is_muted(false);
        }
        stream.push_volume();
    }

    toggleMute() {
        this._stream?.change_is_muted(!this._stream.is_muted);
    }

    /** [{id, name, icon, active}], named as in GNOME's own output menu. */
    outputs() {
        const result = [];
        for (const id of this._outputs) {
            const device = this._control.lookup_output_id(id);
            if (!device)
                continue;
            const description = device.get_description();
            const origin = device.get_origin();
            result.push({id, name: origin ? `${description} – ${origin}` : description,
                icon: device.get_gicon() ?? 'audio-speakers-symbolic', active: id === this._activeOutput});
        }
        return result.sort((a, b) => a.name.localeCompare(b.name));
    }

    selectOutput(id) {
        const device = this._control.lookup_output_id(id);
        if (device)
            this._control.change_output(device);
    }

    destroy() {
        this._stream?.disconnectObject(this);
        this._stream = null;
        this._control.disconnectObject(this);
    }
}

/**
 * Screen brightness through the shell's brightness manager, wired the way
 * GNOME's own brightness slider is (js/ui/status/brightness.js): its global
 * scale can appear, disappear or be replaced, announced by 'changed'.
 */
class BrightnessService {
    constructor(slider, onChanged) {
        this._slider = slider;
        this._onChanged = onChanged;
        this._scale = null;
        this._manager = Main.brightnessManager ?? null;
        this._manager?.connectObject('changed', () => this._bind(), this);
        this._sliderId = this._slider.connect('notify::value', () => {
            if (!this._blocked && this._scale)
                this._scale.value = this._slider.value;
        });
        this._bind();
    }

    _bind() {
        const scale = this._manager?.globalScale ?? null;
        if (scale !== this._scale) {
            this._scale?.disconnectObject(this);
            this._scale = scale;
            scale?.connectObject('notify::value', () => this._update(), this);
        }
        this._update();
    }

    _update() {
        if (this._scale) {
            this._blocked = true;
            this._slider.value = this._scale.value;
            this._blocked = false;
        }
        this._onChanged();
    }

    get available() {
        return Boolean(this._scale);
    }

    destroy() {
        this._slider.disconnect(this._sliderId);
        this._scale?.disconnectObject(this);
        this._scale = null;
        this._manager?.disconnectObject(this);
    }
}

/** power-profiles-daemon (or tuned-ppd), under its current or older name. */
class PowerProfilesService {
    constructor(onChanged) {
        this._clients = POWER_PROFILES.map(spec => new DBusClient(Gio.BusType.SYSTEM, spec, onChanged));
    }

    get _client() {
        return this._clients.find(c => c.owned) ?? null;
    }

    get profiles() {
        return (this._client?.get('Profiles') ?? []).map(p => p.Profile).filter(Boolean);
    }

    get active() {
        return this._client?.get('ActiveProfile') ?? null;
    }

    get available() {
        return this.profiles.length > 1;
    }

    setActive(profile) {
        this._client?.set('ActiveProfile', GLib.Variant.new_string(profile));
    }

    destroy() {
        this._clients.forEach(c => c.destroy());
    }
}

/** The battery shown by UPower (its display device). */
class BatteryService {
    constructor(onChanged) {
        this._client = new DBusClient(Gio.BusType.SYSTEM, BATTERY, onChanged);
    }

    get present() {
        // Type 2 is a battery; computers without one report another type.
        return this._client.get('IsPresent') === true && this._client.get('Type') === 2;
    }

    get percentage() {
        return Math.round(this._client.get('Percentage') ?? 0);
    }

    get iconName() {
        return this._client.get('IconName') || 'battery-symbolic';
    }

    get status() {
        const state = this._client.get('State');
        if (state === 1) {
            const left = duration(this._client.get('TimeToFull'));
            return left ? _('Full in %s').replace('%s', left) : _('Charging');
        }
        if (state === 4)
            return _('Fully charged');
        if (state === 2) {
            const left = duration(this._client.get('TimeToEmpty'));
            return left ? _('%s left').replace('%s', left) : _('On battery');
        }
        return _('Plugged in');
    }

    destroy() {
        this._client.destroy();
    }
}

/** MPRIS players on the session bus; the one playing (or paused) is shown. */
class MediaService {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._players = new Map();
    }

    // Called whenever the Control Center opens.
    refresh() {
        Gio.DBus.session.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'ListNames', null, new GLib.VariantType('(as)'), Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
                if (this._destroyed)
                    return;
                let names;
                try {
                    [names] = bus.call_finish(res).deepUnpack();
                } catch (e) {
                    warn('cannot list media players', e);
                    return;
                }
                const players = new Set(names.filter(n => n.startsWith(MPRIS_PREFIX)));
                for (const [name, player] of this._players) {
                    if (!players.has(name)) {
                        player.destroy();
                        this._players.delete(name);
                    }
                }
                for (const name of players) {
                    if (!this._players.has(name)) {
                        this._players.set(name, new DBusClient(Gio.BusType.SESSION,
                            [name, '/org/mpris/MediaPlayer2', MPRIS_PLAYER],
                            () => this._onChanged(), Gio.DBusProxyFlags.GET_INVALIDATED_PROPERTIES));
                    }
                }
                this._onChanged();
            });
    }

    /** The player to show: playing first, then paused; or null. */
    get current() {
        const players = [...this._players.values()].filter(p => p.owned);
        return players.find(p => p.get('PlaybackStatus') === 'Playing') ??
            players.find(p => p.get('PlaybackStatus') === 'Paused') ?? null;
    }

    destroy() {
        this._destroyed = true;
        for (const player of this._players.values())
            player.destroy();
        this._players.clear();
    }
}

/** Stay Awake, owned by the jeronix-quick-settings extension (its public API). */
class StayAwakeService {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._watched = null;
        this._unwatch = null;
        this.refresh();
    }

    get _extension() {
        const ext = Main.extensionManager.lookup(STAY_AWAKE_UUID)?.stateObj ?? null;
        return ext?.stayAwakeAvailable ? ext : null;
    }

    // The extension can be enabled or disabled at any time: re-attach.
    refresh() {
        const ext = this._extension;
        if (ext !== this._watched) {
            this._unwatch?.();
            this._unwatch = ext ? ext.watchStayAwake(() => this._onChanged()) : null;
            this._watched = ext;
        }
    }

    get available() {
        return Boolean(this._extension);
    }

    get on() {
        return Boolean(this._extension?.stayAwakeWanted);
    }

    toggle() {
        const ext = this._extension;
        ext?.setStayAwake(!ext.stayAwakeWanted);
        this._onChanged();
    }

    destroy() {
        this._unwatch?.();
        this._unwatch = null;
        this._watched = null;
    }
}

// -- the Control Center ----------------------------------------------------------------

export class ControlCenter {
    /**
     * @param {Gio.Settings} settings - the dock extension's settings
     * @param {string} extensionPath - for the bundled icons
     */
    constructor(settings, extensionPath) {
        this._menu = Main.panel.statusArea.quickSettings?.menu ?? null;
        if (!this._menu)
            return;
        this._settings = settings;
        this._iconDir = `${extensionPath}/icons`;
        this._hidden = new Set();
        this._detailKind = null;

        // Grid and detail list inside a scroll view, so the Control Center
        // fits short screens.
        this.actor = new St.ScrollView({
            style_class: 'jeronix-cc-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            overlay_scrollbars: true,
            x_expand: true,
        });
        this._content = new St.BoxLayout({style_class: 'jeronix-cc', orientation: Clutter.Orientation.VERTICAL,
            x_expand: true});
        this.actor.child = this._content;
        this._layout = new Clutter.GridLayout({column_homogeneous: true, column_spacing: 10, row_spacing: 10});
        this._grid = new St.Widget({style_class: 'jeronix-cc-grid', layout_manager: this._layout, x_expand: true});
        this._content.add_child(this._grid);
        this._detail = new St.BoxLayout({style_class: 'jeronix-cc-detail', orientation: Clutter.Orientation.VERTICAL,
            x_expand: true, visible: false});
        this._content.add_child(this._detail);

        this._modules = new Map();
        this._buildConnectivity();
        this._buildToggles();
        this._buildSliders();
        this._buildMedia();
        this._buildTiles();
        this._built = true;

        this._menu.box.insert_child_at_index(this.actor, 0);
        this._hideGnomeGrid();
        this._menu.actor.add_style_class_name('jeronix-cc-menu');
        this._menu.connectObject('open-state-changed', (m, open) => {
            if (open)
                this._onOpen();
            else
                this._showGrid();
        }, this);
        this._settings.connectObject(
            `changed::${MODULES_KEY}`, () => this._relayout(true),
            `changed::${SOLID_KEY}`, () => this._syncSolid(),
            this);
        this._syncSolid();
        this._sync();
        this._relayout(true);
    }

    // GNOME's own content stays hidden while the Control Center exists.
    _hideGnomeGrid() {
        for (const child of this._menu.box.get_children()) {
            if (child === this.actor || !child.visible)
                continue;
            child.hide();
            this._hidden.add(child);
        }
    }

    _syncSolid() {
        if (this._settings.get_boolean(SOLID_KEY))
            this._menu.actor.add_style_class_name('jeronix-cc-solid');
        else
            this._menu.actor.remove_style_class_name('jeronix-cc-solid');
    }

    _onOpen() {
        this._hideGnomeGrid();
        this._showGrid();
        // Fit the work area of the monitor the menu opens on.
        const monitor = Main.layoutManager.findIndexForActor(this._menu.sourceActor);
        const area = Main.layoutManager.getWorkAreaForMonitor(monitor >= 0 ? monitor : Main.layoutManager.primaryIndex);
        const scale = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        this.actor.style = `max-height: ${Math.max(200, Math.round(area.height / scale) - MARGIN)}px;`;
        this._stayAwake.refresh();
        this._media.refresh();
        this._bluetooth.refresh();
        this._sync();
    }

    _icon(name) {
        return Gio.icon_new_for_string(`${this._iconDir}/jeronix-cc-${name}-symbolic.svg`);
    }

    // -- modules ----------------------------------------------------------------

    _buildConnectivity() {
        this._connectivity = card('jeronix-cc-connectivity');
        this._network = new NetworkService(() => this._sync());
        this._rfkill = new DBusClient(Gio.BusType.SESSION, RFKILL, () => this._sync());
        this._bluetooth = new BluetoothService(() => this._sync());

        this._wifi = new ToggleRow('network-wireless-symbolic', _('Wi-Fi'), () => {
            if (this._network.wifiDevice)
                this._network.setWifiEnabled(!this._network.wifiEnabled);
            else
                this._open('network');
        }, () => (this._network.wifiDevice ? this._showDetail('wifi') : this._open('network')), true);
        this._bt = new ToggleRow('bluetooth-active-symbolic', _('Bluetooth'),
            () => this._rfkill.set('BluetoothAirplaneMode', GLib.Variant.new_boolean(this._bt.circle.checked)),
            () => this._showDetail('bluetooth'), true);
        this._airplane = new ToggleRow('airplane-mode-symbolic', _('Airplane Mode'),
            () => this._rfkill.set('AirplaneMode', GLib.Variant.new_boolean(!this._airplane.circle.checked)));
        this._vpn = new ToggleRow('network-vpn-symbolic', _('VPN'), () => this._showDetail('vpn'),
            () => this._showDetail('vpn'), true);
        this._rows = {'wifi': this._wifi, 'bluetooth': this._bt, 'airplane-mode': this._airplane, 'vpn': this._vpn};
        for (const row of Object.values(this._rows))
            this._connectivity.add_child(row.actor);
        this._modules.set('connectivity', this._connectivity);
    }

    _buildToggles() {
        this._notifications = optionalSettings('org.gnome.desktop.notifications', 'show-banners');
        this._focus = new ToggleRow(this._icon('focus'), _('Do Not Disturb'),
            () => this._notifications.set_boolean('show-banners', !this._notifications.get_boolean('show-banners')),
            () => this._open('notifications'));
        this._notifications?.connectObject('changed::show-banners', () => this._sync(), this);
        this._modules.set('focus', this._wrap(this._focus, 'jeronix-cc-focus'));

        this._stayAwake = new StayAwakeService(() => this._sync());
        this._awake = new ToggleRow(this._icon('stay-awake'), _('Stay Awake'), () => this._stayAwake.toggle());
        this._modules.set('stay-awake', this._wrap(this._awake));

        this._interface = optionalSettings('org.gnome.desktop.interface', 'color-scheme');
        this._dark = new Tile(this._icon('dark-mode'), _('Dark Mode'), () => {
            const dark = this._interface.get_string('color-scheme') === 'prefer-dark';
            this._interface.set_string('color-scheme', dark ? 'prefer-light' : 'prefer-dark');
        }, true);
        this._interface?.connectObject('changed::color-scheme', () => this._sync(), this);
        this._modules.set('dark-mode', this._dark.actor);

        this._color = optionalSettings('org.gnome.settings-daemon.plugins.color', 'night-light-enabled');
        this._night = new Tile('night-light-symbolic', _('Night Light'), () =>
            this._color.set_boolean('night-light-enabled', !this._color.get_boolean('night-light-enabled')), true);
        this._color?.connectObject('changed::night-light-enabled', () => this._sync(), this);
        this._displayConfig = new DBusClient(Gio.BusType.SESSION, DISPLAY_CONFIG, () => this._sync());
        this._modules.set('night-light', this._night.actor);

        this._profiles = new PowerProfilesService(() => this._sync());
        this._power = new ToggleRow(this._icon('power-mode'), _('Power Mode'), () => this._showDetail('power-mode'),
            () => this._showDetail('power-mode'), true);
        this._modules.set('power-mode', this._wrap(this._power));

        this._battery = new BatteryService(() => this._sync());
        this._batteryRow = new ToggleRow('battery-symbolic', _('Battery'), () => this._open('power'),
            () => this._open('power'));
        this._modules.set('battery', this._wrap(this._batteryRow));
    }

    _wrap(row, extraClass = '') {
        const c = card(extraClass, false);
        c.add_child(row.actor);
        return c;
    }

    _buildSliders() {
        this._display = new SliderModule(_('Display'), 'display-brightness-symbolic');
        this._brightness = new BrightnessService(this._display.slider, () => this._sync());
        this._modules.set('display', this._display.actor);

        this._sound = new SliderModule(_('Sound'), 'audio-volume-high-symbolic', {
            onIconClicked: () => this._soundService.toggleMute(),
            onOpen: () => this._showDetail('sound'),
        });
        this._sound.slider.connect('notify::value', () => {
            if (!this._syncing)
                this._soundService.setLevel(this._sound.slider.value);
        });
        this._soundService = new SoundService(() => this._sync());
        this._modules.set('sound', this._sound.actor);
    }

    _buildMedia() {
        this._media = new MediaService(() => this._sync());
        this._mediaModule = card('jeronix-cc-media', false);
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        this._mediaTitle = label('', 'jeronix-cc-row-title');
        this._mediaArtist = label('', 'jeronix-cc-row-status');
        text.add_child(this._mediaTitle);
        text.add_child(this._mediaArtist);
        this._mediaModule.add_child(text);
        const control = (icon, name, method) => {
            const b = new St.Button({style_class: 'jeronix-cc-media-button', can_focus: true, accessible_name: name,
                y_align: Clutter.ActorAlign.CENTER, child: new St.Icon({icon_name: icon})});
            b.connect('clicked', () => this._media.current?.call(method));
            this._mediaModule.add_child(b);
            return b;
        };
        this._prev = control('media-skip-backward-symbolic', _('Previous'), 'Previous');
        this._play = control('media-playback-start-symbolic', _('Play or pause'), 'PlayPause');
        this._next = control('media-skip-forward-symbolic', _('Next'), 'Next');
        this._modules.set('now-playing', this._mediaModule);
    }

    _buildTiles() {
        this._screenshot = new Tile('camera-photo-symbolic', _('Screenshot'), () => {
            this._menu.close();
            Screenshot.showScreenshotUI();
        });
        this._modules.set('screenshot', this._screenshot.actor);
        this._recording = new Tile('media-record-symbolic', _('Record'), () => {
            this._menu.close();
            Screenshot.showScreenRecordingUI();
        });
        this._modules.set('screen-recording', this._recording.actor);
        this._settingsRow = new ToggleRow('emblem-system-symbolic', _('Settings'), () => this._open(null),
            () => this._open(null));
        this._settingsRow.set(false, _('All settings'));
        this._modules.set('settings', this._wrap(this._settingsRow));
    }

    // -- layout -------------------------------------------------------------------

    _available(id) {
        switch (id) {
        case 'wifi':
            return this._network.available;
        case 'bluetooth':
            return this._rfkill.get('BluetoothHasAirplaneMode') === true;
        case 'airplane-mode':
            return this._rfkill.get('ShouldShowAirplaneMode') === true;
        case 'vpn':
            return this._network.vpns().length > 0;
        case 'focus':
            return Boolean(this._notifications);
        case 'stay-awake':
            return this._stayAwake.available;
        case 'dark-mode':
            return Boolean(this._interface);
        case 'night-light':
            // Unknown (no answer yet, older Mutter) counts as supported.
            return Boolean(this._color) && this._displayConfig.get('NightLightSupported') !== false;
        case 'power-mode':
            return this._profiles.available;
        case 'display':
            return this._brightness.available;
        case 'sound':
            return this._soundService.available;
        case 'now-playing':
            return Boolean(this._media.current);
        case 'battery':
            return this._battery.present;
        default:
            return true;
        }
    }

    /** The packed layout for the current settings and hardware. */
    get placed() {
        return pack(blocks(this._settings.get_strv(MODULES_KEY), id => this._available(id)), COLUMNS);
    }

    // Re-attaches modules when the set of visible ones changes.
    _relayout(force = false) {
        if (!this._built || this._destroyed)
            return;
        const placed = this.placed;
        const signature = JSON.stringify(placed.map(b => [b.id, b.col, b.row, b.w, b.h, b.rows ?? []]));
        if (!force && signature === this._signature)
            return;
        this._signature = signature;
        for (const child of this._grid.get_children())
            this._grid.remove_child(child);
        for (const b of placed) {
            if (b.rows) {
                for (const [id, row] of Object.entries(this._rows))
                    row.actor.visible = b.rows.includes(id);
                b.rows.forEach((id, index) => this._connectivity.set_child_at_index(this._rows[id].actor, index));
            }
            this._layout.attach(this._modules.get(b.id), b.col, b.row, b.w, b.h);
        }
        this._placed = placed;
    }

    _open(page) {
        this._menu.close();
        openSettings(page);
    }

    // -- in-place lists (macOS: a module expands into its options) ------------------

    _showDetail(kind) {
        this._detailKind = kind;
        if (kind === 'wifi')
            this._network.requestScan();
        if (kind === 'bluetooth')
            this._bluetooth.refresh();
        this._grid.hide();
        this._detail.show();
        this._renderDetail();
        this._detailBack?.grab_key_focus();
    }

    _showGrid() {
        this._detailKind = null;
        this._detailBack = null;
        this._detail.hide();
        this._detail.destroy_all_children();
        this._grid.show();
    }

    _detailRow(iconSpec, text, checked, onClick, {status = '', busy = false} = {}) {
        const box = new St.BoxLayout({style_class: 'jeronix-cc-list-row', x_expand: true});
        if (iconSpec)
            box.add_child(makeIcon(iconSpec, 'jeronix-cc-list-icon'));
        const texts = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        texts.add_child(label(text, 'jeronix-cc-row-title'));
        if (status)
            texts.add_child(label(status, 'jeronix-cc-row-status'));
        box.add_child(texts);
        if (busy)
            box.add_child(label('…', 'jeronix-cc-row-status'));
        else if (checked)
            box.add_child(new St.Icon({icon_name: 'object-select-symbolic', style_class: 'jeronix-cc-list-check'}));
        const button = new St.Button({style_class: 'jeronix-cc-list-item', can_focus: true, x_expand: true,
            accessible_name: text, child: box});
        button.connect('clicked', () => onClick());
        return button;
    }

    _renderDetail() {
        const kind = this._detailKind;
        if (!kind)
            return;
        // Rebuilt on every change; keep the keyboard on the same row.
        const focused = global.stage.key_focus;
        let focusIndex = -1;
        if (focused && this._list?.contains(focused))
            focusIndex = this._list.get_children().findIndex(c => c === focused || c.contains(focused));
        const backFocused = focused && focused === this._detailBack;
        this._detail.destroy_all_children();

        const titles = {'wifi': _('Wi-Fi'), 'bluetooth': _('Bluetooth'), 'vpn': _('VPN'),
            'sound': _('Sound Output'), 'power-mode': _('Power Mode')};
        const header = new St.BoxLayout({style_class: 'jeronix-cc-detail-header', x_expand: true});
        this._detailBack = new St.Button({style_class: 'jeronix-cc-back', can_focus: true, accessible_name: _('Back'),
            child: new St.Icon({icon_name: 'go-previous-symbolic', style_class: 'jeronix-cc-list-icon'})});
        this._detailBack.connect('clicked', () => this._showGrid());
        header.add_child(this._detailBack);
        header.add_child(label(titles[kind], 'jeronix-cc-detail-title'));
        this._detail.add_child(header);

        this._list = new St.BoxLayout({style_class: 'jeronix-cc-module jeronix-cc-list',
            orientation: Clutter.Orientation.VERTICAL, x_expand: true});
        this._detail.add_child(this._list);
        const list = this._list;
        const empty = text => list.add_child(label(text, 'jeronix-cc-list-empty'));
        let page = null;
        if (kind === 'wifi') {
            page = 'wifi';
            const on = this._network.wifiEnabled;
            list.add_child(this._detailRow(null, _('Wi-Fi'), on, () => this._network.setWifiEnabled(!on),
                {status: on ? _('On') : _('Off')}));
            if (on) {
                const found = this._network.networks();
                if (!found.length)
                    empty(_('Looking for networks…'));
                for (const n of found.slice(0, 30)) {
                    const status = [n.active ? _('Connected') : '', n.secure ? _('Secured') : _('Open'),
                        n.saved && !n.active ? _('Saved') : ''].filter(Boolean).join(' · ');
                    list.add_child(this._detailRow(signalIcon(n.strength), n.ssid, n.active, () => {
                        // A network that needs a new password is joined in Settings.
                        if (!n.active && !this._network.join(n))
                            this._open('wifi');
                    }, {status}));
                }
            }
        } else if (kind === 'bluetooth') {
            page = 'bluetooth';
            const on = this._rfkill.get('BluetoothAirplaneMode') === false;
            list.add_child(this._detailRow(null, _('Bluetooth'), on,
                () => this._rfkill.set('BluetoothAirplaneMode', GLib.Variant.new_boolean(on)),
                {status: on ? _('On') : _('Off')}));
            if (on) {
                if (!this._bluetooth.devices.length)
                    empty(_('No paired devices'));
                for (const d of this._bluetooth.devices) {
                    list.add_child(this._detailRow(d.icon, d.name, d.connected, () => this._bluetooth.toggle(d),
                        {status: d.connected ? _('Connected') : _('Not connected'), busy: this._bluetooth.isBusy(d)}));
                }
            }
        } else if (kind === 'vpn') {
            page = 'network';
            const vpns = this._network.vpns();
            if (!vpns.length)
                empty(_('No VPN connections'));
            for (const v of vpns) {
                list.add_child(this._detailRow('network-vpn-symbolic', v.name, Boolean(v.active),
                    () => this._network.toggleVpn(v), {status: v.active ? _('Connected') : _('Not connected')}));
            }
        } else if (kind === 'sound') {
            page = 'sound';
            const outputs = this._soundService.outputs();
            if (!outputs.length)
                empty(_('No sound outputs'));
            for (const o of outputs)
                list.add_child(this._detailRow(o.icon, o.name, o.active, () => this._soundService.selectOutput(o.id)));
        } else if (kind === 'power-mode') {
            page = 'power';
            const names = {'power-saver': _('Power Saver'), 'balanced': _('Balanced'), 'performance': _('Performance')};
            for (const p of this._profiles.profiles) {
                list.add_child(this._detailRow(null, names[p] ?? p, p === this._profiles.active,
                    () => this._profiles.setActive(p)));
            }
        }
        const more = new St.Button({style_class: 'jeronix-cc-more', can_focus: true, x_align: Clutter.ActorAlign.START,
            label: _('%s Settings…').replace('%s', titles[kind])});
        more.connect('clicked', () => this._open(page));
        this._detail.add_child(more);

        if (backFocused)
            this._detailBack.grab_key_focus();
        else if (focusIndex >= 0)
            list.get_child_at_index(Math.min(focusIndex, list.get_n_children() - 1))?.grab_key_focus();
    }

    // -- state ----------------------------------------------------------------------

    _sync() {
        if (!this._built || this._destroyed)
            return;
        this._syncing = true;
        try {
            const net = this._network;
            if (net.wifiDevice) {
                this._wifi.setTitle(_('Wi-Fi'));
                this._wifi.set(net.wifiEnabled, !net.wifiEnabled ? _('Off') : net.wifiName ?? _('Not connected'),
                    net.wifiEnabled ? 'network-wireless-symbolic' : 'network-wireless-offline-symbolic');
                this._wifi.sensitive = !net.wifiBlocked;
            } else {
                this._wifi.setTitle(_('Network'));
                this._wifi.set(net.wiredConnected, net.wiredConnected ? _('Connected') : _('Disconnected'),
                    'network-wired-symbolic');
                this._wifi.sensitive = true;
            }

            const rf = this._rfkill;
            const btOn = rf.get('BluetoothAirplaneMode') === false;
            const connected = this._bluetooth.devices.filter(d => d.connected).map(d => d.name);
            this._bt.set(btOn, !btOn ? _('Off') : connected.length ? connected.join(', ') : _('On'),
                btOn ? 'bluetooth-active-symbolic' : 'bluetooth-disabled-symbolic');
            this._bt.sensitive = rf.get('BluetoothHardwareAirplaneMode') !== true;
            const airplane = rf.get('AirplaneMode') === true;
            this._airplane.set(airplane, airplane ? _('On') : _('Off'));
            this._airplane.sensitive = rf.get('HardwareAirplaneMode') !== true;

            const activeVpn = net.vpns().find(v => v.active);
            this._vpn.set(Boolean(activeVpn), activeVpn ? activeVpn.name : _('Not connected'));

            if (this._notifications) {
                const dnd = !this._notifications.get_boolean('show-banners');
                this._focus.set(dnd, dnd ? _('On') : _('Off'));
            }
            const awake = this._stayAwake.on;
            this._awake.set(awake, awake ? _('Screen stays on') : _('Off'));
            if (this._interface)
                this._dark.set(this._interface.get_string('color-scheme') === 'prefer-dark');
            if (this._color)
                this._night.set(this._color.get_boolean('night-light-enabled'));
            const profileNames = {'power-saver': _('Power Saver'), 'balanced': _('Balanced'),
                'performance': _('Performance')};
            const profile = this._profiles.active;
            this._power.set(Boolean(profile) && profile !== 'balanced', profileNames[profile] ?? profile ?? '');

            if (this._battery.present) {
                this._batteryRow.set(false, `${this._battery.percentage}% · ${this._battery.status}`,
                    this._battery.iconName);
            }

            const sound = this._soundService;
            const level = sound.level;
            this._sound.slider.value = level;
            this._sound.icon.icon_name = sound.muted || level === 0 ? 'audio-volume-muted-symbolic'
                : level < 0.34 ? 'audio-volume-low-symbolic'
                    : level < 0.67 ? 'audio-volume-medium-symbolic' : 'audio-volume-high-symbolic';
            this._sound.openButton.visible = sound.outputs().length > 1;

            const player = this._media.current;
            if (player) {
                const metadata = player.get('Metadata') ?? {};
                const artists = metadata['xesam:artist'];
                this._mediaTitle.text = metadata['xesam:title'] || _('Unknown title');
                this._mediaArtist.text = Array.isArray(artists) ? artists.join(', ') : artists ?? '';
                const playing = player.get('PlaybackStatus') === 'Playing';
                this._play.child.icon_name = playing ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic';
                this._prev.reactive = player.get('CanGoPrevious') !== false;
                this._next.reactive = player.get('CanGoNext') !== false;
            }
        } finally {
            this._syncing = false;
        }
        this._relayout();
        if (this._detailKind)
            this._renderDetail();
    }

    // Read-only state for tests.
    debugState() {
        if (!this._menu)
            return null;
        return {
            open: this._menu.isOpen,
            parentIsQuickSettings: this.actor.get_parent() === this._menu.box,
            gnomeVisible: this._menu.box.get_children().filter(c => c !== this.actor && c.visible).length,
            modules: (this._placed ?? []).map(b => (b.rows ? `connectivity(${b.rows.join(',')})` : b.id)),
            layout: (this._placed ?? []).map(b => [b.id, b.col, b.row, b.w, b.h]),
            detail: this._detailKind,
            detailRows: this._detailKind ? this._list?.get_n_children() ?? 0 : 0,
            wifi: this._wifi.state,
            bluetooth: this._bt.state,
            focus: this._focus.state,
            stayAwake: this._awake.state,
            darkMode: this._dark.state,
            solid: this._menu.actor.has_style_class_name('jeronix-cc-solid'),
        };
    }

    /** Opens a list in place (tests); returns whether that kind exists. */
    debugShowDetail(kind) {
        if (!DETAIL_KINDS.includes(kind))
            return false;
        this._showDetail(kind);
        return true;
    }

    destroy() {
        if (!this._menu)
            return;
        this._destroyed = true;
        // Close first, without animation, so GNOME's grid never appears in an
        // open menu while it is given back.
        if (this._menu.isOpen)
            this._menu.close(false);
        this._menu.disconnectObject(this);
        this._settings.disconnectObject(this);
        this._menu.actor.remove_style_class_name('jeronix-cc-menu');
        this._menu.actor.remove_style_class_name('jeronix-cc-solid');
        for (const service of [this._network, this._rfkill, this._bluetooth, this._soundService, this._brightness,
            this._profiles, this._battery, this._media, this._stayAwake, this._displayConfig])
            service.destroy();
        for (const s of [this._notifications, this._interface, this._color])
            s?.disconnectObject(this);
        // Modules not on the grid are not inside the Control Center's actor.
        for (const actor of this._modules.values()) {
            if (!actor.get_parent())
                actor.destroy();
        }
        this.actor.destroy();
        for (const child of this._hidden)
            child.show();
        this._hidden.clear();
        this._menu = null;
    }
}
