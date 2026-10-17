// SPDX-License-Identifier: GPL-3.0-or-later
//
// The JERONIX Start menu: a shell popup (not an application window) opened
// from the taskbar's Start button or Super+J. Search on top, pinned apps
// (the dock favorites) or all apps in a grid, and the user's name with
// settings and power actions at the bottom.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {alphabetical, search} from './search.js';

const COLUMNS = 6;
const TILE_ICON = 36;
const SETTINGS_ID = 'io.jeronix.Settings.desktop';

export class StartMenu {
    constructor(sourceActor, side) {
        this._appSystem = Shell.AppSystem.get_default();
        this.menu = new PopupMenu.PopupMenu(sourceActor, 0.5, side);
        this.menu.actor.add_style_class_name('jeronix-start-menu');
        Main.uiGroup.add_child(this.menu.actor);
        this.menu.actor.hide();
        this._manager = new PopupMenu.PopupMenuManager(sourceActor);
        this._manager.addMenu(this.menu);

        const content = new St.BoxLayout({style_class: 'jeronix-start', orientation: Clutter.Orientation.VERTICAL});
        this.menu.box.add_child(content);

        this._entry = new St.Entry({
            style_class: 'jeronix-start-search',
            hint_text: _('Type to search apps'),
            can_focus: true,
            x_expand: true,
            primary_icon: new St.Icon({icon_name: 'system-search-symbolic', style_class: 'jeronix-start-search-icon'}),
        });
        this._entry.clutter_text.connect('text-changed', () => this._refresh());
        this._entry.clutter_text.connect('activate', () => this._launchFirst());
        content.add_child(this._entry);

        const header = new St.BoxLayout({style_class: 'jeronix-start-header'});
        this._title = new St.Label({style_class: 'jeronix-start-title', x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        this._toggle = new St.Button({style_class: 'jeronix-start-toggle', can_focus: true});
        this._toggle.connect('clicked', () => {
            this._view = this._view === 'all' ? 'pinned' : 'all';
            this._refresh();
        });
        header.add_child(this._title);
        header.add_child(this._toggle);
        content.add_child(header);

        this._grid = new St.Widget({
            style_class: 'jeronix-start-grid',
            layout_manager: new Clutter.GridLayout({column_homogeneous: true}),
        });
        const gridBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL});
        gridBox.add_child(this._grid);
        this._empty = new St.Label({text: _('No apps match your search'), style_class: 'jeronix-start-empty',
            x_align: Clutter.ActorAlign.CENTER, visible: false});
        gridBox.add_child(this._empty);
        this._scroll = new St.ScrollView({
            style_class: 'jeronix-start-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            overlay_scrollbars: true,
            child: gridBox,
            y_expand: true,
        });
        content.add_child(this._scroll);

        content.add_child(this._footer());

        this.menu.connect('open-state-changed', (m, open) => {
            if (!open)
                return;
            this._view = 'pinned';
            this._entry.set_text('');
            this._refresh();
            // Focus the search field once the menu is mapped, so typing works.
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                this._entry.grab_key_focus();
                return GLib.SOURCE_REMOVE;
            });
        });
        this._view = 'pinned';
    }

    _footer() {
        const footer = new St.BoxLayout({style_class: 'jeronix-start-footer'});
        const user = new St.BoxLayout({style_class: 'jeronix-start-user', x_expand: true});
        user.add_child(new St.Icon({icon_name: 'avatar-default-symbolic', style_class: 'jeronix-start-avatar'}));
        user.add_child(new St.Label({text: GLib.get_real_name() || GLib.get_user_name(),
            y_align: Clutter.ActorAlign.CENTER}));
        footer.add_child(user);

        const actions = SystemActions.getDefault();
        const button = (icon, label, callback, property) => {
            const b = new St.Button({
                style_class: 'jeronix-start-action', can_focus: true, accessible_name: label,
                child: new St.Icon({icon_name: icon}),
            });
            b.connect('clicked', () => {
                this.menu.close();
                callback();
            });
            if (property)
                actions.bind_property(property, b, 'visible', GObject.BindingFlags.SYNC_CREATE);
            footer.add_child(b);
            return b;
        };
        button('emblem-system-symbolic', _('JERONIX Settings'), () => {
            const app = this._appSystem.lookup_app(SETTINGS_ID) ?? this._appSystem.lookup_app('org.gnome.Settings.desktop');
            app?.activate();
        });
        button('system-lock-screen-symbolic', _('Lock'), () => actions.activateLockScreen(), 'can-lock-screen');
        button('system-log-out-symbolic', _('Log Out'), () => actions.activateLogout(), 'can-logout');
        button('system-shutdown-symbolic', _('Power Off'), () => actions.activatePowerOff(), 'can-power-off');
        return footer;
    }

    _entries() {
        const entries = [];
        for (const info of this._appSystem.get_installed()) {
            if (!info.should_show())
                continue;
            const app = this._appSystem.lookup_app(info.get_id());
            if (!app)
                continue;
            entries.push({
                id: info.get_id(), app, name: app.get_name(),
                generic: info.get_generic_name?.() ?? '', description: info.get_description() ?? '',
                keywords: info.get_keywords?.() ?? [], executable: GLib.path_get_basename(info.get_executable() ?? ''),
            });
        }
        return entries;
    }

    visibleApps() {
        const query = this._entry.get_text().trim();
        if (query)
            return search(this._entries(), query).map(e => e.app);
        if (this._view === 'all')
            return alphabetical(this._entries()).map(e => e.app);
        return AppFavorites.getAppFavorites().getFavorites();
    }

    _refresh() {
        const query = this._entry.get_text().trim();
        this._title.text = query ? _('Best matches') : this._view === 'all' ? _('All apps') : _('Pinned');
        this._toggle.label = this._view === 'all' ? _('‹ Back') : _('All apps ›');
        this._toggle.visible = !query;
        this._grid.destroy_all_children();
        const layout = this._grid.layout_manager;
        const apps = this.visibleApps();
        apps.forEach((app, i) => layout.attach(this._tile(app), i % COLUMNS, Math.floor(i / COLUMNS), 1, 1));
        this._empty.visible = apps.length === 0;
        this._apps = apps;
    }

    _tile(app) {
        const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, style_class: 'jeronix-start-tile-box'});
        box.add_child(app.create_icon_texture(TILE_ICON));
        const label = new St.Label({text: app.get_name(), style_class: 'jeronix-start-tile-label',
            x_align: Clutter.ActorAlign.CENTER});
        label.clutter_text.ellipsize = 3; // Pango.EllipsizeMode.END
        box.add_child(label);
        const tile = new St.Button({style_class: 'jeronix-start-tile', can_focus: true,
            accessible_name: app.get_name(), child: box});
        tile.connect('clicked', () => this._launch(app));
        return tile;
    }

    _launch(app) {
        this.menu.close();
        Main.overview.hide();
        app.activate();
    }

    _launchFirst() {
        if (this._apps?.length)
            this._launch(this._apps[0]);
    }

    get isOpen() {
        return this.menu.isOpen;
    }

    get title() {
        return this._title.text;
    }

    get query() {
        return this._entry.get_text();
    }

    setQuery(text) {
        this._entry.set_text(text);
    }

    toggle() {
        this.menu.toggle();
    }

    destroy() {
        this.menu.close();
        this._manager.removeMenu(this.menu);
        this.menu.destroy();
    }
}
