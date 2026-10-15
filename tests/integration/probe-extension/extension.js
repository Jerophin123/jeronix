// SPDX-License-Identifier: GPL-3.0-or-later
//
// Test-only extension loaded into isolated headless shells by
// tests/integration/extension_lifecycle.py and theme_lifecycle.py. GNOME
// Shell's Eval method is disabled outside unsafe mode, so this exposes the
// few queries tests need.

import Gio from 'gi://Gio';
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
