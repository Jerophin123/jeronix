// SPDX-License-Identifier: GPL-3.0-or-later
//
// Screen brightness for JERONIX Settings, over D-Bus.
//
// GNOME Shell owns screen brightness (its brightness manager drives every
// monitor's backlight, dimming and auto brightness) but offers no D-Bus
// method to set it; only its own slider can. This service gives JERONIX
// Settings the same control as that slider: it follows the brightness
// manager's global scale, the way js/ui/status/brightness.js does, and
// publishes it on the shell's own connection:
//
//   bus name  org.gnome.Shell (the shell's)
//   path      /io/jeronix/Shell/Brightness
//   interface io.jeronix.Shell.Brightness
//     Available  b   read        a screen with adjustable brightness exists
//     Brightness d   read/write  0..1, as on GNOME's slider
//
// Both properties announce changes (PropertiesChanged), whoever made them:
// keyboard keys, the Control Center, Quick Settings or Settings itself.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export const OBJECT_PATH = '/io/jeronix/Shell/Brightness';
export const INTERFACE = 'io.jeronix.Shell.Brightness';

const XML = `<node>
  <interface name="${INTERFACE}">
    <property name="Available" type="b" access="read"/>
    <property name="Brightness" type="d" access="readwrite"/>
  </interface>
</node>`;

export class BrightnessService {
    constructor() {
        this._scale = null;
        this._manager = Main.brightnessManager ?? null;
        this._dbus = Gio.DBusExportedObject.wrapJSObject(XML, this);
        // The global scale can appear, disappear or be replaced (monitors
        // plugged in or out); the manager announces it with 'changed'.
        this._manager?.connectObject('changed', () => this._bind(), this);
        this._bind();
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
    }

    _bind() {
        const scale = this._manager?.globalScale ?? null;
        if (scale === this._scale)
            return;
        this._scale?.disconnectObject(this);
        this._scale = scale;
        scale?.connectObject('notify::value', () => this._emit('Brightness'), this);
        this._emit('Available');
        this._emit('Brightness');
    }

    _emit(name) {
        const value = name === 'Available'
            ? GLib.Variant.new_boolean(this.Available)
            : GLib.Variant.new_double(this.Brightness);
        this._dbus?.emit_property_changed(name, value);
    }

    // -- D-Bus properties ----------------------------------------------------

    get Available() {
        return Boolean(this._scale);
    }

    get Brightness() {
        return this._scale?.value ?? 0;
    }

    set Brightness(value) {
        if (this._scale && Number.isFinite(value))
            this._scale.value = Math.min(1, Math.max(0, value));
    }

    destroy() {
        this._dbus?.unexport();
        this._dbus = null;
        this._scale?.disconnectObject(this);
        this._scale = null;
        this._manager?.disconnectObject(this);
        this._manager = null;
    }
}
