// SPDX-License-Identifier: GPL-3.0-or-later
//
// Test-only extension loaded into isolated headless shells by
// tests/integration/extension_lifecycle.py. GNOME Shell's Eval method is
// disabled outside unsafe mode, so this exposes the few queries tests need.

import Gio from 'gi://Gio';

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
