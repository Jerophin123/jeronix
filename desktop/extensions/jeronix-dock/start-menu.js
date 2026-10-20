// SPDX-License-Identifier: GPL-3.0-or-later
//
// The JERONIX Start menu: a shell popup (not an application window) opened
// from the taskbar's Start or Search button, Super or Super+J. Like Windows
// 11 it sits centered above a centered taskbar: search on top, pinned apps
// (its own list, 'start-pinned-apps', separate from the taskbar's),
// recommended apps (the most used ones), all apps, and a full-width footer
// with the user's name and settings and power actions.
//
// Right-click an app (or press the Menu key or Shift+F10 on it) to pin it
// to or unpin it from Start, move it to the front, or pin it to the
// taskbar. That context menu is drawn inside the Start menu, so it needs no
// second pointer grab.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {available, isPinned, move, pin, unpin, visibleToFullIndex} from './pins.js';
import {alphabetical, search} from './search.js';

const COLUMNS = 6;
const TILE_ICON = 32;
const RECOMMENDED = 6;
const RECOMMENDED_ICON = 32;
const SETTINGS_ID = 'io.jeronix.Settings.desktop';
const SUPER_KEYS = [Clutter.KEY_Super_L, Clutter.KEY_Super_R];
const PINS_KEY = 'start-pinned-apps';
const HIDDEN_KEY = 'start-hidden-apps';
// GNOME's taskbar pins (the dock shows them); written directly so GNOME's
// "pinned to the dash" message does not appear.
const FAVORITES_KEY = 'favorite-apps';

export class StartMenu {
    /**
     * @param {St.Side} side - which side of the anchor the taskbar is on
     * @param {Function} anchorRect - returns {x, y, width, height}: the
     *   area the menu opens against (the taskbar's top edge, centered)
     * @param {Gio.Settings} settings - the dock extension's settings
     */
    constructor(side, anchorRect, settings) {
        this._appSystem = Shell.AppSystem.get_default();
        this._anchorRect = anchorRect;
        this._settings = settings;
        // An invisible actor the menu points at. Moved before each opening,
        // so the menu is centered on the screen rather than on the button.
        this._anchor = new St.Widget({name: 'jeronixStartAnchor', opacity: 0, reactive: false});
        Main.layoutManager.uiGroup.add_child(this._anchor);

        this.menu = new PopupMenu.PopupMenu(this._anchor, 0.5, side);
        this.menu.actor.add_style_class_name('jeronix-start-menu');
        Main.uiGroup.add_child(this.menu.actor);
        this.menu.actor.hide();
        this._manager = new PopupMenu.PopupMenuManager(this._anchor);
        this._manager.addMenu(this.menu);
        // Super closes the menu again (it opens it when the menu is closed).
        // Only a whole press and release made while the menu is open counts:
        // GNOME emits 'overlay-key' on release and may then deliver the
        // held-back press of the same keystroke to the menu.
        this.menu.actor.connect('key-press-event', (actor, event) => {
            if (!SUPER_KEYS.includes(event.get_key_symbol()))
                return Clutter.EVENT_PROPAGATE;
            this._superPressed = true;
            return Clutter.EVENT_STOP;
        });
        this.menu.actor.connect('key-release-event', (actor, event) => {
            if (!SUPER_KEYS.includes(event.get_key_symbol()))
                return Clutter.EVENT_PROPAGATE;
            if (this._superPressed)
                this.menu.close();
            this._superPressed = false;
            return Clutter.EVENT_STOP;
        });

        // The menu's content, with a layer above it for the app context menu.
        const root = new St.Widget({layout_manager: new Clutter.BinLayout()});
        this.menu.box.add_child(root);
        const content = new St.BoxLayout({style_class: 'jeronix-start', orientation: Clutter.Orientation.VERTICAL});
        this._content = content;
        root.add_child(content);
        this._layer = new St.Widget({x_expand: true, y_expand: true, reactive: false});
        // A click beside the context menu closes it (and nothing else).
        this._layer.connect('button-press-event', () => {
            this._closeContext();
            return Clutter.EVENT_STOP;
        });
        root.add_child(this._layer);
        this._context = null;

        const body = new St.BoxLayout({style_class: 'jeronix-start-body', orientation: Clutter.Orientation.VERTICAL,
            y_expand: true});
        content.add_child(body);
        content.add_child(this._footer());

        this._entry = new St.Entry({
            style_class: 'jeronix-start-search',
            hint_text: _('Search for apps'),
            can_focus: true,
            x_expand: true,
            primary_icon: new St.Icon({icon_name: 'system-search-symbolic', style_class: 'jeronix-start-search-icon'}),
        });
        this._entry.clutter_text.connect('text-changed', () => this._refresh());
        this._entry.clutter_text.connect('activate', () => this._launchFirst());
        body.add_child(this._entry);

        // Pinned, All apps or search results.
        const [header, title, toggle] = this._header();
        this._title = title;
        this._toggle = toggle;
        this._toggle.connect('clicked', () => {
            this._view = this._view === 'all' ? 'pinned' : 'all';
            this._refresh();
        });
        body.add_child(header);

        this._grid = new St.Widget({
            style_class: 'jeronix-start-grid',
            layout_manager: new Clutter.GridLayout(),
            x_align: Clutter.ActorAlign.START,
        });
        const gridBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL});
        gridBox.add_child(this._grid);
        this._empty = new St.Label({text: '', style_class: 'jeronix-start-empty',
            x_align: Clutter.ActorAlign.CENTER, visible: false});
        this._empty.clutter_text.line_wrap = true;
        gridBox.add_child(this._empty);
        this._scroll = new St.ScrollView({
            style_class: 'jeronix-start-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            overlay_scrollbars: true,
            child: gridBox,
            y_expand: true,
        });
        body.add_child(this._scroll);

        // Recommended: the most used apps that are not pinned to Start.
        this._recommended = new St.BoxLayout({style_class: 'jeronix-start-recommended',
            orientation: Clutter.Orientation.VERTICAL});
        const [recHeader] = this._header(_('Recommended'));
        this._recommended.add_child(recHeader);
        this._recGrid = new St.Widget({
            style_class: 'jeronix-start-recommended-grid',
            layout_manager: new Clutter.GridLayout(),
            x_align: Clutter.ActorAlign.START,
        });
        this._recommended.add_child(this._recGrid);
        this._recEmpty = new St.Label({style_class: 'jeronix-start-empty',
            text: _('Apps you use often will appear here'), x_align: Clutter.ActorAlign.START});
        this._recommended.add_child(this._recEmpty);
        body.add_child(this._recommended);

        this.menu.connect('open-state-changed', (m, open) => {
            this._superPressed = false;
            this._closeContext(false);
            if (!open)
                return;
            this._view = 'pinned';
            this._entry.set_text('');
            this._refresh();
            // Focus the search field once the menu is mapped, so typing works.
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (this.menu.isOpen)
                    this._entry.grab_key_focus();
                return GLib.SOURCE_REMOVE;
            });
        });
        // Pins change from this menu, JERONIX Settings or gsettings; an open
        // menu follows them without being rebuilt (extension.js leaves these
        // keys out of its rebuild).
        this._settings.connectObject(
            `changed::${PINS_KEY}`, () => this._refreshIfOpen(),
            `changed::${HIDDEN_KEY}`, () => this._refreshIfOpen(),
            this);
        this._view = 'pinned';
    }

    _header(text = '') {
        const header = new St.BoxLayout({style_class: 'jeronix-start-header'});
        const title = new St.Label({text, style_class: 'jeronix-start-title', x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        header.add_child(title);
        const toggle = new St.Button({style_class: 'jeronix-start-toggle', can_focus: true});
        if (!text)
            header.add_child(toggle);
        return [header, title, toggle];
    }

    _footer() {
        const footer = new St.BoxLayout({style_class: 'jeronix-start-footer', x_expand: true});
        const user = new St.BoxLayout({style_class: 'jeronix-start-user', x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        user.add_child(new St.Icon({icon_name: 'avatar-default-symbolic', style_class: 'jeronix-start-avatar'}));
        user.add_child(new St.Label({text: GLib.get_real_name() || GLib.get_user_name(),
            style_class: 'jeronix-start-user-name', y_align: Clutter.ActorAlign.CENTER}));
        footer.add_child(user);

        const actions = SystemActions.getDefault();
        this._actions = [];
        const button = (icon, label, callback, property) => {
            const b = new St.Button({
                style_class: 'jeronix-start-action', can_focus: true, accessible_name: label,
                y_align: Clutter.ActorAlign.CENTER,
                child: new St.Icon({icon_name: icon}),
            });
            b.connect('clicked', () => {
                this.menu.close();
                callback();
            });
            b.connect('notify::hover', () => (b.hover ? this._tooltip(b, label) : this._tooltip(null)));
            if (property)
                actions.bind_property(property, b, 'visible', GObject.BindingFlags.SYNC_CREATE);
            footer.add_child(b);
            this._actions.push([label, b]);
        };
        button('emblem-system-symbolic', _('Settings'), () => {
            const app = this._appSystem.lookup_app(SETTINGS_ID) ?? this._appSystem.lookup_app('org.gnome.Settings.desktop');
            app?.activate();
        });
        button('system-lock-screen-symbolic', _('Lock'), () => actions.activateLockScreen(), 'can-lock-screen');
        button('system-log-out-symbolic', _('Log Out'), () => actions.activateLogout(), 'can-logout');
        button('system-reboot-symbolic', _('Restart'), () => actions.activateRestart(), 'can-restart');
        button('system-shutdown-symbolic', _('Power Off'), () => actions.activatePowerOff(), 'can-power-off');

        this._tip = new St.Label({style_class: 'jeronix-dock-label', visible: false});
        Main.layoutManager.uiGroup.add_child(this._tip);
        return footer;
    }

    _tooltip(actor, text) {
        if (!actor) {
            this._tip.hide();
            return;
        }
        this._tip.text = text;
        this._tip.show();
        Main.layoutManager.uiGroup.set_child_above_sibling(this._tip, null);
        const [x, y] = actor.get_transformed_position();
        const [w] = actor.get_transformed_size();
        const [, tw] = this._tip.get_preferred_width(-1);
        const [, th] = this._tip.get_preferred_height(tw);
        this._tip.set_position(Math.round(x + w / 2 - tw / 2), Math.round(y - th - 6));
    }

    // -- apps and pins ------------------------------------------------------

    _hidden() {
        return new Set(this._settings.get_strv(HIDDEN_KEY));
    }

    _pins() {
        return this._settings.get_strv(PINS_KEY);
    }

    _setPins(ids) {
        this._settings.set_strv(PINS_KEY, ids);
    }

    // Installed, shown in menus, and not hidden from Start.
    _isListed(id, hidden) {
        if (hidden.has(id))
            return false;
        const app = this._appSystem.lookup_app(id);
        return Boolean(app) && app.get_app_info()?.should_show?.() !== false;
    }

    /** The pinned apps that are listed, in pinned order (desktop IDs). */
    pinnedIds() {
        const hidden = this._hidden();
        return available(this._pins(), id => this._isListed(id, hidden));
    }

    _entries() {
        const hidden = this._hidden();
        const entries = [];
        for (const info of this._appSystem.get_installed()) {
            if (!info.should_show() || hidden.has(info.get_id()))
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
        return this.pinnedIds().map(id => this._appSystem.lookup_app(id));
    }

    recommendedApps() {
        const pinned = new Set(this._pins());
        const hidden = this._hidden();
        return Shell.AppUsage.get_default().get_most_used()
            .filter(app => app && !pinned.has(app.get_id()) && !hidden.has(app.get_id()) &&
                app.get_app_info()?.should_show?.() !== false)
            .slice(0, RECOMMENDED);
    }

    _refreshIfOpen() {
        if (this.menu.isOpen)
            this._refresh();
    }

    _refresh() {
        // The context menu belongs to a tile that is about to be replaced.
        this._closeContext(false);
        const query = this._entry.get_text().trim();
        this._title.text = query ? _('Best matches') : this._view === 'all' ? _('All apps') : _('Pinned');
        this._toggle.label = this._view === 'all' ? _('‹ Back') : _('All apps ›');
        this._toggle.visible = !query;
        this._grid.destroy_all_children();
        const layout = this._grid.layout_manager;
        const apps = this.visibleApps();
        apps.forEach((app, i) => layout.attach(this._tile(app), i % COLUMNS, Math.floor(i / COLUMNS), 1, 1));
        this._empty.text = query ? _('No apps match your search')
            : _('Nothing is pinned. Right-click an app in All apps and choose Pin to Start.');
        this._empty.visible = apps.length === 0;
        this._apps = apps;

        // Recommended only beside the pinned apps, as in Windows 11.
        const showRecommended = !query && this._view === 'pinned';
        this._recommended.visible = showRecommended;
        this._recGrid.destroy_all_children();
        if (showRecommended) {
            const recLayout = this._recGrid.layout_manager;
            const recommended = this.recommendedApps();
            recommended.forEach((app, i) => recLayout.attach(this._row(app), i % 2, Math.floor(i / 2), 1, 1));
            this._recEmpty.visible = recommended.length === 0;
        }
    }

    _tile(app) {
        const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, style_class: 'jeronix-start-tile-box'});
        const icon = app.create_icon_texture(TILE_ICON);
        icon.x_align = Clutter.ActorAlign.CENTER;
        box.add_child(icon);
        const label = new St.Label({text: app.get_name(), style_class: 'jeronix-start-tile-label',
            x_align: Clutter.ActorAlign.CENTER});
        label.clutter_text.ellipsize = 3; // Pango.EllipsizeMode.END
        box.add_child(label);
        const tile = new St.Button({style_class: 'jeronix-start-tile', can_focus: true,
            accessible_name: app.get_name(), child: box});
        tile.connect('clicked', () => this._launch(app));
        this._addContextTriggers(tile, app);
        return tile;
    }

    _row(app) {
        const box = new St.BoxLayout({style_class: 'jeronix-start-row-box', x_expand: true,
            x_align: Clutter.ActorAlign.START});
        box.add_child(app.create_icon_texture(RECOMMENDED_ICON));
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, y_align: Clutter.ActorAlign.CENTER,
            x_expand: true});
        const name = new St.Label({text: app.get_name(), style_class: 'jeronix-start-row-name'});
        name.clutter_text.ellipsize = 3;
        text.add_child(name);
        const detail = app.get_app_info()?.get_generic_name?.() || app.get_description?.() || '';
        if (detail) {
            const sub = new St.Label({text: detail, style_class: 'jeronix-start-row-detail'});
            sub.clutter_text.ellipsize = 3;
            text.add_child(sub);
        }
        box.add_child(text);
        const row = new St.Button({style_class: 'jeronix-start-row', can_focus: true,
            accessible_name: app.get_name(), child: box});
        row.connect('clicked', () => this._launch(app));
        this._addContextTriggers(row, app);
        return row;
    }

    // -- app context menu ---------------------------------------------------

    // Right-click, the Menu key or Shift+F10 open the context menu. St.Button
    // reacts to the primary button only, so the secondary press reaches here.
    _addContextTriggers(button, app) {
        button.connect('button-press-event', (actor, event) => {
            if (event.get_button() !== Clutter.BUTTON_SECONDARY)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = event.get_coords();
            this._openContext(app, button, x, y);
            return Clutter.EVENT_STOP;
        });
        button.connect('key-press-event', (actor, event) => {
            const key = event.get_key_symbol();
            const shift = (event.get_state() & Clutter.ModifierType.SHIFT_MASK) !== 0;
            if (key !== Clutter.KEY_Menu && !(key === Clutter.KEY_F10 && shift))
                return Clutter.EVENT_PROPAGATE;
            const [bx, by] = button.get_transformed_position();
            const [bw, bh] = button.get_transformed_size();
            this._openContext(app, button, bx + bw / 2, by + bh / 2);
            return Clutter.EVENT_STOP;
        });
    }

    /** The context menu's entries for app: [[label, callback], ...]. */
    contextActions(app) {
        const id = app.get_id();
        const pins = this._pins();
        const actions = [];
        if (isPinned(pins, id)) {
            actions.push([_('Unpin from Start'), () => this._setPins(unpin(pins, id))]);
            const visible = this.pinnedIds();
            if (visible.indexOf(id) > 0) {
                actions.push([_('Move to front'),
                    () => this._setPins(move(pins, id, visibleToFullIndex(pins, visible, 0)))]);
            }
        } else {
            actions.push([_('Pin to Start'), () => this._setPins(pin(pins, id))]);
        }
        const favorites = global.settings.get_strv(FAVORITES_KEY);
        if (favorites.includes(id)) {
            actions.push([_('Unpin from taskbar'),
                () => global.settings.set_strv(FAVORITES_KEY, favorites.filter(f => f !== id))]);
        } else if (!app.is_window_backed()) {
            actions.push([_('Pin to taskbar'), () => global.settings.set_strv(FAVORITES_KEY, [...favorites, id])]);
        }
        return actions;
    }

    _openContext(app, source, stageX, stageY) {
        this._closeContext(false);
        const actions = this.contextActions(app);
        const box = new St.BoxLayout({style_class: 'jeronix-start-context', orientation: Clutter.Orientation.VERTICAL,
            reactive: true});
        // Escape closes only this menu, not the whole Start menu.
        box.connect('key-press-event', (actor, event) => {
            if (event.get_key_symbol() !== Clutter.KEY_Escape)
                return Clutter.EVENT_PROPAGATE;
            this._closeContext();
            return Clutter.EVENT_STOP;
        });
        // Clicks inside the menu must not reach the layer below, which closes it.
        box.connect('button-press-event', () => Clutter.EVENT_STOP);
        const buttons = actions.map(([label, callback]) => {
            const b = new St.Button({style_class: 'jeronix-start-context-item', can_focus: true,
                x_expand: true, accessible_name: label,
                child: new St.Label({text: label, x_align: Clutter.ActorAlign.START, x_expand: true})});
            b.connect('clicked', () => {
                this._closeContext(false);
                callback();
                this._entry.grab_key_focus();
            });
            box.add_child(b);
            return b;
        });
        this._layer.add_child(box);
        this._layer.reactive = true;
        this._context = {box, source, app, labels: actions.map(([label]) => label)};

        // At the pointer (or the focused app), kept inside the Start menu.
        const [ok, lx, ly] = this._layer.transform_stage_point(stageX, stageY);
        const [, w] = box.get_preferred_width(-1);
        const [, h] = box.get_preferred_height(w);
        const [lw, lh] = this._layer.get_size();
        const x = ok ? Math.min(Math.max(0, lx), Math.max(0, lw - w)) : 0;
        const y = ok ? Math.min(Math.max(0, ly), Math.max(0, lh - h)) : 0;
        box.set_position(Math.round(x), Math.round(y));
        buttons[0]?.grab_key_focus();
    }

    // refocus: give the keyboard back to the app the menu was opened on.
    _closeContext(refocus = true) {
        if (!this._context)
            return;
        const {box, source} = this._context;
        this._context = null;
        this._layer.reactive = false;
        box.destroy();
        if (refocus && this.menu.isOpen && source.get_stage())
            source.grab_key_focus();
    }

    // -- launching ----------------------------------------------------------

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

    // Read-only layout facts for tests.
    debugState() {
        const rect = actor => {
            const [x, y] = actor.get_transformed_position();
            const [w, h] = actor.get_transformed_size();
            return [x, y, w, h].map(Math.round);
        };
        return {
            rect: this.isOpen ? rect(this._content) : null,
            footerRect: this.isOpen ? rect(this._content.get_last_child()) : null,
            recommendedVisible: this.isOpen && this._recommended.visible,
            actions: this._actions.filter(([, b]) => b.visible).map(([label]) => label),
            pinned: this.pinnedIds(),
            context: this._context ? {app: this._context.app.get_id(), actions: this._context.labels} : null,
        };
    }

    toggle() {
        if (!this.menu.isOpen) {
            const {x, y, width, height} = this._anchorRect();
            this._anchor.set_position(Math.round(x), Math.round(y));
            this._anchor.set_size(Math.max(1, Math.round(width)), Math.max(1, Math.round(height)));
        }
        this.menu.toggle();
    }

    destroy() {
        this._settings.disconnectObject(this);
        this._closeContext(false);
        this.menu.close();
        this._manager.removeMenu(this.menu);
        this.menu.destroy();
        this._tip.destroy();
        this._anchor.destroy();
    }
}
