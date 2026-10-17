// SPDX-License-Identifier: GPL-3.0-or-later
//
// JERONIX Panel: replaces the Activities button with the JERONIX menu, adds a
// workspace switcher and the focused application's context to the top bar.
// The clock, Quick Settings and every status indicator stay GNOME's own.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';
import {AppMenu} from 'resource:///org/gnome/shell/ui/appMenu.js';
import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {JERONIX_APPS, launchApp} from './apps.js';

const JeronixMenuButton = GObject.registerClass(
class JeronixMenuButton extends PanelMenu.Button {
    constructor(extension, settings) {
        super(0.0, _('JERONIX'), false);
        this.add_style_class_name('jeronix-menu-button');
        this.accessible_name = _('JERONIX menu');
        this._settings = settings;

        const box = new St.BoxLayout({style_class: 'jeronix-menu-box'});
        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(`${extension.path}/icons/jeronix-symbolic.svg`),
            style_class: 'jeronix-menu-icon',
        });
        this._label = new St.Label({
            text: 'JERONIX',
            style_class: 'jeronix-menu-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);
        settings.connectObject('changed::show-menu-label', () => this._sync(), this);
        this._sync();
        this._buildMenu();
    }

    _sync() {
        this._label.visible = this._settings.get_boolean('show-menu-label');
    }

    _item(label, callback, icon = null) {
        const item = icon
            ? new PopupMenu.PopupImageMenuItem(label, icon)
            : new PopupMenu.PopupMenuItem(label);
        item.connect('activate', () => callback());
        this.menu.addMenuItem(item);
        return item;
    }

    _buildMenu() {
        this.menu.actor.add_style_class_name('jeronix-menu');
        this._item(_('Search Applications'), () => launchApp(JERONIX_APPS.launcher),
            'system-search-symbolic');
        this._item(_('Overview'), () => Main.overview.toggle(), 'view-grid-symbolic');
        this._item(_('All Applications'), () => Main.overview.showApps(), 'view-app-grid-symbolic');
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(_('JERONIX')));
        this._item(_('Layout Studio'), () => launchApp(JERONIX_APPS.layoutStudio),
            'view-dual-symbolic');
        this._item(_('JERONIX Settings'), () => launchApp(JERONIX_APPS.settings),
            'preferences-system-symbolic');
        this._item(_('System Information'), () => launchApp(JERONIX_APPS.systemInfo),
            'help-about-symbolic');
        this._item(_('Welcome Tour'), () => launchApp(JERONIX_APPS.welcome),
            'starred-symbolic');
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._item(_('GNOME Settings'), () => launchApp('org.gnome.Settings.desktop'),
            'emblem-system-symbolic');

        const actions = SystemActions.getDefault();
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const lock = this._item(_('Lock Screen'), () => actions.activateLockScreen(),
            'system-lock-screen-symbolic');
        actions.bind_property('can-lock-screen', lock, 'visible', GObject.BindingFlags.SYNC_CREATE);
        const logout = this._item(_('Log Out…'), () => actions.activateLogout(),
            'system-log-out-symbolic');
        actions.bind_property('can-logout', logout, 'visible', GObject.BindingFlags.SYNC_CREATE);
        const power = this._item(_('Power Off…'), () => actions.activatePowerOff(),
            'system-shutdown-symbolic');
        actions.bind_property('can-power-off', power, 'visible', GObject.BindingFlags.SYNC_CREATE);
    }
});

// Numbered workspace pills. Click to switch, scroll to step through.
const WorkspaceSwitcher = GObject.registerClass(
class WorkspaceSwitcher extends PanelMenu.Button {
    constructor() {
        super(0.0, _('Workspaces'), true);
        this.add_style_class_name('jeronix-workspaces');
        this._box = new St.BoxLayout({style_class: 'jeronix-workspaces-box'});
        this.add_child(this._box);

        const manager = global.workspace_manager;
        manager.connectObject(
            'notify::n-workspaces', () => this._rebuild(),
            'active-workspace-changed', () => this._syncActive(),
            this);
        this.connect('scroll-event', (actor, event) => this._onScroll(event));
        this._rebuild();
    }

    _rebuild() {
        this._box.destroy_all_children();
        const manager = global.workspace_manager;
        for (let i = 0; i < manager.n_workspaces; i++) {
            const pill = new St.Button({
                label: `${i + 1}`,
                style_class: 'jeronix-workspace-pill',
                y_align: Clutter.ActorAlign.CENTER,
                can_focus: true,
                accessible_name: _('Workspace %d').format(i + 1),
            });
            pill.connect('clicked', () =>
                manager.get_workspace_by_index(i)?.activate(global.get_current_time()));
            this._box.add_child(pill);
        }
        this._syncActive();
    }

    _syncActive() {
        const active = global.workspace_manager.get_active_workspace_index();
        this._box.get_children().forEach((pill, i) => {
            if (i === active)
                pill.add_style_pseudo_class('checked');
            else
                pill.remove_style_pseudo_class('checked');
        });
    }

    _onScroll(event) {
        const direction = event.get_scroll_direction();
        const step = {
            [Clutter.ScrollDirection.UP]: -1,
            [Clutter.ScrollDirection.LEFT]: -1,
            [Clutter.ScrollDirection.DOWN]: 1,
            [Clutter.ScrollDirection.RIGHT]: 1,
        }[direction];
        if (!step)
            return Clutter.EVENT_PROPAGATE;
        const manager = global.workspace_manager;
        const target = manager.get_active_workspace().get_neighbor(
            step < 0 ? Meta.MotionDirection.LEFT : Meta.MotionDirection.RIGHT);
        target.activate(global.get_current_time());
        return Clutter.EVENT_STOP;
    }

    get workspaceCount() {
        return this._box.get_n_children();
    }
});

// Focused application: icon and name, with GNOME's app menu (real window
// list and actions) on click.
const WindowContext = GObject.registerClass(
class WindowContext extends PanelMenu.Button {
    constructor() {
        super(0.0, _('Focused application'), true);
        this.add_style_class_name('jeronix-window-context');
        const box = new St.BoxLayout({style_class: 'jeronix-window-context-box'});
        this._icon = new St.Icon({style_class: 'jeronix-window-context-icon'});
        this._label = new St.Label({y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._menu = new AppMenu(this, St.Side.TOP, {favoritesSection: true, showSingleWindows: true});
        this.setMenu(this._menu);
        Main.panel.menuManager.addMenu(this._menu);

        Shell.WindowTracker.get_default().connectObject('notify::focus-app', () => this._sync(), this);
        Main.overview.connectObject('showing', () => this._sync(), 'hidden', () => this._sync(), this);
        this._sync();
    }

    _sync() {
        const app = Main.overview.visible ? null : Shell.WindowTracker.get_default().focus_app;
        this.visible = Boolean(app);
        if (!app)
            return;
        this._icon.gicon = app.get_icon();
        this._label.text = app.get_name();
        this._menu.setApp(app);
    }

    get appName() {
        return this.visible ? this._label.text : '';
    }
});

export default class JeronixPanelExtension extends Extension {
    enable() {
        // GNOME 50 can call enable() twice when enabled-extensions and
        // disabled-extensions change in quick succession (two overlapping
        // async passes in extensionSystem.js); the second call is a no-op.
        if (this._settings)
            return;
        // A previous instance that failed half-way may have left its items
        // registered; remove them so enabling always succeeds.
        for (const role of ['jeronix-menu', 'jeronix-workspaces', 'jeronix-window-context'])
            Main.panel.statusArea[role]?.destroy();
        this._settings = this.getSettings();
        this._menuButton = new JeronixMenuButton(this, this._settings);
        Main.panel.addToStatusArea('jeronix-menu', this._menuButton, 0, 'left');

        this._activities = Main.panel.statusArea.activities;
        this._settings.connectObject(
            'changed::show-workspaces', () => this._syncOptional(),
            'changed::show-window-context', () => this._syncOptional(),
            'changed::hide-activities', () => this._syncOptional(),
            this);
        this._syncOptional();
        Main.panel.add_style_class_name('jeronix-panel');

        Main.wm.addKeybinding('launcher-shortcut', this._settings, Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => launchApp(JERONIX_APPS.launcher));
    }

    _syncOptional() {
        const wanted = {
            workspaces: this._settings.get_boolean('show-workspaces'),
            context: this._settings.get_boolean('show-window-context'),
        };
        if (wanted.workspaces && !this._workspaces) {
            this._workspaces = new WorkspaceSwitcher();
            Main.panel.addToStatusArea('jeronix-workspaces', this._workspaces, 1, 'left');
        } else if (!wanted.workspaces && this._workspaces) {
            this._workspaces.destroy();
            this._workspaces = null;
        }
        if (wanted.context && !this._context) {
            this._context = new WindowContext();
            Main.panel.addToStatusArea('jeronix-window-context', this._context, 2, 'left');
        } else if (!wanted.context && this._context) {
            this._context.destroy();
            this._context = null;
        }
        // The overview stays reachable from the JERONIX menu, the Super key
        // and the hot corner, so hiding Activities removes no function.
        this._activities.container.visible = !this._settings.get_boolean('hide-activities');
    }

    disable() {
        Main.wm.removeKeybinding('launcher-shortcut');
        Main.panel.remove_style_class_name('jeronix-panel');
        this._settings.disconnectObject(this);
        this._activities.container.visible = true;
        this._activities = null;
        this._context?.destroy();
        this._context = null;
        this._workspaces?.destroy();
        this._workspaces = null;
        this._menuButton.destroy();
        this._menuButton = null;
        this._settings = null;
    }

    // Read-only state for tests (tests/integration/desktop_lifecycle.py).
    debugState() {
        if (!this._settings)
            return null;
        return {
            menuButton: Boolean(this._menuButton?.get_parent()),
            menuItems: this._menuButton?.menu._getMenuItems().filter(i => i.label).map(i => i.label.text) ?? [],
            activitiesVisible: Main.panel.statusArea.activities.container.visible,
            workspaces: this._workspaces?.workspaceCount ?? 0,
            focusedApp: this._context?.appName ?? '',
        };
    }
}
