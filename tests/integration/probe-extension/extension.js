// SPDX-License-Identifier: GPL-3.0-or-later
//
// Test-only extension loaded into isolated headless shells by
// tests/integration/extension_lifecycle.py and theme_lifecycle.py. GNOME
// Shell's Eval method is disabled outside unsafe mode, so this exposes the
// few queries tests need.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.jeronix.Test.Probe">
    <method name="FindToggles">
      <arg type="s" direction="in" name="title"/>
      <arg type="u" direction="out" name="count"/>
      <arg type="b" direction="out" name="anyChecked"/>
    </method>
    <method name="ClickToggle">
      <arg type="s" direction="in" name="title"/>
      <arg type="b" direction="out" name="clicked"/>
    </method>
    <method name="StyleColor">
      <arg type="s" direction="in" name="chainJson"/>
      <arg type="s" direction="in" name="property"/>
      <arg type="s" direction="out" name="color"/>
    </method>
    <method name="CustomStylesheets">
      <arg type="as" direction="out" name="paths"/>
    </method>
    <method name="SetColorScheme">
      <arg type="s" direction="in" name="scheme"/>
    </method>
    <method name="ExtensionDebug">
      <arg type="s" direction="in" name="uuid"/>
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="SetExtensionSetting">
      <arg type="s" direction="in" name="uuid"/>
      <arg type="s" direction="in" name="key"/>
      <arg type="s" direction="in" name="value"/>
    </method>
    <method name="Screenshot">
      <arg type="s" direction="in" name="path"/>
    </method>
    <method name="MovePointer">
      <arg type="d" direction="in" name="x"/>
      <arg type="d" direction="in" name="y"/>
    </method>
    <method name="WindowAction">
      <arg type="s" direction="in" name="title"/>
      <arg type="s" direction="in" name="action"/>
      <arg type="b" direction="out" name="found"/>
    </method>
    <method name="State">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="SetOverview">
      <arg type="b" direction="in" name="visible"/>
    </method>
    <method name="PressKeys">
      <arg type="s" direction="in" name="combo"/>
    </method>
    <method name="SetSetting">
      <arg type="s" direction="in" name="schema"/>
      <arg type="s" direction="in" name="key"/>
      <arg type="s" direction="in" name="value"/>
    </method>
    <method name="Click">
      <arg type="d" direction="in" name="x"/>
      <arg type="d" direction="in" name="y"/>
    </method>
  </interface>
</node>`;

function findToggles(title) {
    const found = [];
    const walk = actor => {
        if (actor.title === title && typeof actor.checked === 'boolean')
            found.push(actor);
        for (const child of actor.get_children())
            walk(child);
    };
    walk(Main.panel.statusArea.quickSettings.menu.actor);
    return found;
}

class Probe {
    FindToggles(title) {
        const toggles = findToggles(title);
        return [toggles.length, toggles.some(t => t.checked)];
    }

    ClickToggle(title) {
        const [toggle] = findToggles(title);
        toggle?.emit('clicked', 1); // primary button
        return Boolean(toggle);
    }

    // Resolves one color property on the innermost of a chain of temporary
    // widgets, e.g. [{name: 'panel'}, {style: 'panel-button'}]. Returns
    // '#rrggbbaa', or '' if the property is unset. For 'box-shadow' the
    // shadow color is returned.
    StyleColor(chainJson, property) {
        const chain = JSON.parse(chainJson);
        const root = new St.Widget();
        let parent = root;
        let leaf = root;
        for (const spec of chain) {
            leaf = new St.Widget({
                name: spec.name ?? null,
                style_class: spec.style ?? null,
                pseudo_class: spec.pseudo ?? null,
            });
            parent.add_child(leaf);
            parent = leaf;
        }
        Main.layoutManager.uiGroup.add_child(root);
        try {
            const node = leaf.get_theme_node();
            let color = null;
            if (property === 'box-shadow') {
                color = node.get_box_shadow()?.color ?? null;
            } else {
                const [found, c] = node.lookup_color(property, false);
                color = found ? c : null;
            }
            if (!color)
                return '';
            return `#${[color.red, color.green, color.blue, color.alpha]
                .map(v => v.toString(16).padStart(2, '0')).join('')}`;
        } finally {
            root.destroy();
        }
    }

    CustomStylesheets() {
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        return theme.get_custom_stylesheets().map(f => f.get_path());
    }

    SetColorScheme(scheme) {
        new Gio.Settings({schema_id: 'org.gnome.desktop.interface'})
            .set_string('color-scheme', scheme);
    }

    // JSON from an extension's debugState(), or 'null'.
    ExtensionDebug(uuid) {
        const ext = Main.extensionManager.lookup(uuid);
        return JSON.stringify(ext?.stateObj?.debugState?.() ?? null);
    }

    SetExtensionSetting(uuid, key, value) {
        const ext = Main.extensionManager.lookup(uuid);
        const settings = ext.stateObj.getSettings();
        const type = settings.settings_schema.get_key(key).get_value_type();
        settings.set_value(key, GLib.Variant.parse(type, value, null, null));
    }

    // Asynchronous: the file appears once the frame has been captured.
    Screenshot(path) {
        const file = Gio.File.new_for_path(path);
        const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
        new Shell.Screenshot().screenshot(false, stream)
            .then(() => stream.close(null))
            .catch(e => console.error(`probe screenshot: ${e.message}`));
    }

    MovePointer(x, y) {
        if (!this._pointer) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._pointer = seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
        }
        this._pointer.notify_absolute_motion(global.get_current_time() * 1000, x, y);
    }

    WindowAction(title, action) {
        const win = global.get_window_actors().map(a => a.meta_window)
            .find(w => w.get_title() === title);
        if (!win)
            return false;
        if (action === 'maximize')
            win.maximize();
        else if (action === 'unmaximize')
            win.unmaximize();
        else if (action === 'activate')
            Main.activateWindow(win);
        else if (action === 'minimize')
            win.minimize();
        return true;
    }

    // 'Super+j': modifiers are held while the last key is pressed.
    PressKeys(combo) {
        if (!this._keyboard) {
            const seat = Clutter.get_default_backend().get_default_seat();
            this._keyboard = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        }
        const names = {Super: 'Super_L', Ctrl: 'Control_L', Alt: 'Alt_L', Shift: 'Shift_L'};
        const keyvals = combo.split('+').map(k => Clutter[`KEY_${names[k] ?? k}`]);
        const time = () => global.get_current_time() * 1000;
        for (const k of keyvals)
            this._keyboard.notify_keyval(time(), k, Clutter.KeyState.PRESSED);
        for (const k of [...keyvals].reverse())
            this._keyboard.notify_keyval(time(), k, Clutter.KeyState.RELEASED);
    }

    // Any GSettings key, value in GVariant text form (e.g. 'true').
    SetSetting(schema, key, value) {
        const settings = new Gio.Settings({schema_id: schema});
        const type = settings.settings_schema.get_key(key).get_value_type();
        settings.set_value(key, GLib.Variant.parse(type, value, null, null));
    }

    // Moves the virtual pointer and clicks the primary button.
    Click(x, y) {
        this.MovePointer(x, y);
        const time = () => global.get_current_time() * 1000;
        this._pointer.notify_button(time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        this._pointer.notify_button(time(), Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
    }

    SetOverview(visible) {
        if (visible)
            Main.overview.show();
        else
            Main.overview.hide();
    }

    State() {
        const monitor = Main.layoutManager.primaryMonitor;
        return JSON.stringify({
            overview: Main.overview.visible,
            overviewAnimating: Main.overview.animationInProgress,
            monitor: [monitor.x, monitor.y, monitor.width, monitor.height],
            windows: global.get_window_actors().map(a => {
                const r = a.meta_window.get_frame_rect();
                return {title: a.meta_window.get_title(), rect: [r.x, r.y, r.width, r.height],
                    maximized: a.meta_window.is_maximized?.() ?? null};
            }),
            workspaces: global.workspace_manager.n_workspaces,
            activitiesVisible: Main.panel.statusArea.activities?.container.visible ?? null,
            panelVisible: Main.panel.visible,
            overviewDash: Main.overview.dash
                ? {visible: Main.overview.dash.visible, height: Math.round(Main.overview.dash.height)} : null,
            quickSettingsParent: Main.panel.statusArea.quickSettings?.container.get_parent()?.name ||
                Main.panel.statusArea.quickSettings?.container.get_parent()?.style_class || null,
            dateMenuParent: Main.panel.statusArea.dateMenu?.container.get_parent()?.name ||
                Main.panel.statusArea.dateMenu?.container.get_parent()?.style_class || null,
        });
    }
}

export default class TestProbeExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, new Probe());
        this._dbus.export(Gio.DBus.session, '/org/jeronix/Test/Probe');
        this._nameId = Gio.bus_own_name(Gio.BusType.SESSION, 'org.jeronix.Test.Probe',
            Gio.BusNameOwnerFlags.NONE, null, null, null);
    }

    disable() {
        Gio.bus_unown_name(this._nameId);
        this._dbus.unexport();
        this._dbus = null;
    }
}
