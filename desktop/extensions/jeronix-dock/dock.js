// SPDX-License-Identifier: GPL-3.0-or-later
//
// The JERONIX dock: a floating bar of favorite and running applications
// built from GNOME Shell's own app icons, so launching, window activation,
// running indicators, app menus and drag-and-drop behave like the rest of
// the shell.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppDisplay from 'resource:///org/gnome/shell/ui/appDisplay.js';
import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {WindowPreviews} from './previews.js';
import {Geometry, ITEM_PADDING, fitIconSize, dropIndex} from './geometry.js';

const SHOW_TIME = 200;
const HIDE_DELAY = 500;
const PREVIEW_DELAY = 450;
const MIN_ICON_SIZE = 24;
const LAUNCHER_ID = 'io.jeronix.Launcher.desktop';

const MENU_SIDE = {bottom: St.Side.BOTTOM, left: St.Side.LEFT, right: St.Side.RIGHT};

const MAGNIFY = [1.35, 1.15]; // hovered icon, direct neighbors
const BOUNCE_HEIGHT = 14;
const BOUNCE_TIME = 170;
const LABEL_DELAY = 250;
// Where icons grow from: the screen edge the dock sits on.
const PIVOTS = {bottom: [0.5, 1], left: [0, 0.5], right: [1, 0.5]};

function animationsEnabled() {
    return St.Settings.get().enable_animations;
}

const DockItem = GObject.registerClass(
class DockItem extends AppDisplay.AppIcon {
    _init(app, side, position) {
        super._init(app, {setSizeManually: true, showLabel: false, popupMenuSide: side});
        this.add_style_class_name('jeronix-dock-item');
        this.accessible_name = app.get_name();
        this._position = position;
        this.icon.set_pivot_point(...PIVOTS[position]);
    }

    // macOS-style launch bounce instead of GNOME's zoom-out; nothing with
    // reduced motion.
    animateLaunch() {
        if (!animationsEnabled())
            return;
        const away = {bottom: ['translation_y', -1], left: ['translation_x', 1],
            right: ['translation_x', -1]}[this._position];
        const bounce = (n) => {
            if (n === 0)
                return;
            this.icon.ease({
                [away[0]]: away[1] * BOUNCE_HEIGHT,
                duration: BOUNCE_TIME,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => this.icon.ease({
                    [away[0]]: 0,
                    duration: BOUNCE_TIME,
                    mode: Clutter.AnimationMode.EASE_IN_QUAD,
                    onComplete: () => bounce(n - 1),
                }),
            });
        };
        bounce(2);
    }

    setMagnification(scale) {
        this.icon.ease({
            scale_x: scale,
            scale_y: scale,
            duration: animationsEnabled() ? 120 : 0,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    get magnification() {
        return this.icon.scale_x;
    }

    // The dock handles drops itself (see Dock.acceptDrop).
    scaleAndFade() {
    }

    undoScaleAndFade() {
    }

    handleDragOver() {
        return DND.DragMotionResult.CONTINUE;
    }

    acceptDrop() {
        return false;
    }
});

export const Dock = GObject.registerClass(
class Dock extends St.Widget {
    constructor(settings, extensionPath) {
        super({
            name: 'jeronixDockContainer',
            reactive: true,
            track_hover: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this._settings = settings;
        this._position = settings.get_string('position');
        this._behavior = settings.get_string('behavior');
        this._vertical = this._position !== 'bottom';
        this._iconSize = settings.get_int('icon-size');
        this._shown = true;
        this._hideTimeout = 0;
        this._previewTimeout = 0;
        this._syncTimeout = 0;

        this._dock = new St.BoxLayout({
            style_class: `jeronix-dock jeronix-dock-${this._position}`,
            orientation: this._vertical ? Clutter.Orientation.VERTICAL : Clutter.Orientation.HORIZONTAL,
            // The container's extra margin sits on the screen-edge side.
            x_align: {bottom: Clutter.ActorAlign.CENTER, left: Clutter.ActorAlign.END,
                right: Clutter.ActorAlign.START}[this._position],
            y_align: this._vertical ? Clutter.ActorAlign.CENTER : Clutter.ActorAlign.START,
        });
        this.add_child(this._dock);

        // Windows 11-style Start (JERONIX Launcher) and Search (GNOME's
        // system-wide search) at the head of the bar.
        this._startButton = new St.Button({
            style_class: 'jeronix-dock-item jeronix-dock-start',
            can_focus: true,
            accessible_name: _('Start: JERONIX Launcher'),
            child: new St.Icon({gicon: Gio.icon_new_for_string(`${extensionPath}/icons/jeronix-start.svg`)}),
        });
        this._startButton.connect('clicked', () => this._openLauncher());
        this._searchButton = new St.Button({
            style_class: 'jeronix-dock-item jeronix-dock-search',
            can_focus: true,
            accessible_name: _('Search'),
            child: new St.Icon({icon_name: 'system-search-symbolic'}),
        });
        this._searchButton.connect('clicked', () => Main.overview.show());
        for (const [button, label] of [[this._startButton, _('Start')], [this._searchButton, _('Search')]]) {
            button.connect('notify::hover', () => this._onButtonHover(button, label));
            this._dock.add_child(button);
        }
        this._startButton.visible = settings.get_boolean('show-start-button');
        this._searchButton.visible = settings.get_boolean('show-search-button');

        this._box = new St.BoxLayout({
            style_class: 'jeronix-dock-items',
            orientation: this._dock.orientation,
        });
        this._box._delegate = this;
        // Items sit directly in the bar so magnified icons can rise above it;
        // only when they overflow do they move into a scroll view (which clips).
        this._scroll = new St.ScrollView({
            style_class: 'jeronix-dock-scroll',
            hscrollbar_policy: this._vertical ? St.PolicyType.NEVER : St.PolicyType.AUTOMATIC,
            vscrollbar_policy: this._vertical ? St.PolicyType.AUTOMATIC : St.PolicyType.NEVER,
            overlay_scrollbars: true,
            visible: false,
        });
        this._dock.add_child(this._box);
        this._dock.add_child(this._scroll);

        this._label = new St.Label({style_class: 'jeronix-dock-label', visible: false});
        Main.layoutManager.addTopChrome(this._label);
        this._labelTimeout = 0;

        this._separator = new St.Widget({style_class: 'jeronix-dock-separator', y_expand: this._vertical});
        this._dock.add_child(this._separator);

        this._appsButton = new St.Button({
            style_class: 'jeronix-dock-item jeronix-dock-apps',
            can_focus: true,
            accessible_name: _('Applications'),
            child: new St.Icon({icon_name: 'view-app-grid-symbolic'}),
        });
        this._appsButton.connect('clicked', () => this._openLauncher());
        this._dock.add_child(this._appsButton);

        // Thin strip at the screen edge that reveals a hidden dock.
        this._edge = new St.Widget({name: 'jeronixDockEdge', reactive: true, opacity: 0});
        this._edge.connect('enter-event', () => this._reveal());

        this._previews = new WindowPreviews(this, MENU_SIDE[this._position]);

        Main.layoutManager.addChrome(this, {
            affectsStruts: this._behavior === 'always',
            trackFullscreen: true,
        });
        Main.layoutManager.addChrome(this._edge, {trackFullscreen: true});
        Main.ctrlAltTabManager.addGroup(this._dock, _('Dock'), 'user-bookmarks-symbolic', {
            focusCallback: () => {
                this._show();
                (this._startButton.visible ? this._startButton : this._box.get_first_child() ?? this._appsButton)
                    .grab_key_focus();
            },
        });

        this.connect('notify::hover', () => {
            if (!this.hover) {
                this._magnify(null);
                this._hideLabel();
            }
            this._sync();
        });
        this._dock.connect('notify::allocation', () => this._queuePlace());
        this._appSystem = Shell.AppSystem.get_default();
        this._appSystem.connectObject(
            'installed-changed', () => this._redisplay(),
            'app-state-changed', () => this._redisplay(),
            this);
        AppFavorites.getAppFavorites().connectObject('changed', () => this._redisplay(), this);
        Shell.WindowTracker.get_default().connectObject('notify::focus-app', () => this._syncFocus(), this);
        Main.layoutManager.connectObject('monitors-changed', () => this._relayout(), this);
        Main.overview.connectObject(
            'showing', () => this._hide(true),
            'hidden', () => this._sync(),
            this);
        global.display.connectObject(
            'restacked', () => this._queueSync(),
            'window-created', (d, win) => this._trackWindow(win),
            this);
        global.workspace_manager.connectObject('active-workspace-changed', () => this._queueSync(), this);
        global.stage.connectObject('notify::key-focus', () => this._sync(), this);
        for (const actor of global.get_window_actors())
            this._trackWindow(actor.meta_window);

        this._redisplay();
    }

    _trackWindow(win) {
        win?.connectObject(
            'position-changed', () => this._queueSync(),
            'size-changed', () => this._queueSync(),
            'notify::minimized', () => this._queueSync(),
            this);
    }

    // -- content ----------------------------------------------------------

    _apps() {
        const favorites = AppFavorites.getAppFavorites().getFavorites();
        const ids = new Set(favorites.map(a => a.get_id()));
        const running = this._settings.get_boolean('show-running')
            ? this._appSystem.get_running().filter(a => !ids.has(a.get_id()))
            : [];
        return {favorites, running};
    }

    _redisplay() {
        const {favorites, running} = this._apps();
        this._box.destroy_all_children();
        const side = MENU_SIDE[this._position];
        for (const app of [...favorites, ...running]) {
            const item = new DockItem(app, side, this._position);
            item.connect('notify::hover', () => this._onItemHover(item));
            item.connect('menu-state-changed', (i, open) => {
                this._menuOpen = open;
                if (open)
                    this._previews.close();
                this._sync();
            });
            if (this._vertical) {
                item._dot.x_align = this._position === 'left' ? Clutter.ActorAlign.START : Clutter.ActorAlign.END;
                item._dot.y_align = Clutter.ActorAlign.CENTER;
            }
            this._box.add_child(item);
        }
        this._favoriteCount = favorites.length;
        this._separator.visible = this._box.get_n_children() > 0 && this._settings.get_boolean('show-apps-button');
        this._appsButton.visible = this._settings.get_boolean('show-apps-button');
        this._syncFocus();
        this._relayout();
    }

    _syncFocus() {
        const focus = Shell.WindowTracker.get_default().focus_app;
        for (const item of this._box.get_children()) {
            if (item.app === focus)
                item.add_style_class_name('jeronix-dock-focused');
            else
                item.remove_style_class_name('jeronix-dock-focused');
        }
    }

    _openLauncher() {
        const launcher = this._appSystem.lookup_app(LAUNCHER_ID);
        if (launcher)
            launcher.activate();
        else
            Main.overview.showApps();
    }

    // -- geometry ---------------------------------------------------------

    _relayout() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || this._destroyed)
            return;
        const panelHeight = Main.layoutManager.panelBox.height;
        const geometry = new Geometry(this._position, monitor, panelHeight);
        const buttons = [this._startButton, this._searchButton, this._appsButton].filter(b => b.visible);
        const fit = fitIconSize({
            items: this._box.get_n_children(),
            extras: buttons.length,
            preferred: this._settings.get_int('icon-size'),
            minimum: MIN_ICON_SIZE,
            available: geometry.available,
        });
        this._iconSize = fit.iconSize;
        for (const item of this._box.get_children())
            item.icon.setIconSize(this._iconSize);
        for (const button of [this._startButton, this._searchButton, this._appsButton]) {
            const glyph = button === this._startButton ? 0.9 : 0.6;
            button.child.icon_size = Math.round(this._iconSize * glyph);
            button.set_size(this._iconSize + ITEM_PADDING, this._iconSize + ITEM_PADDING);
        }

        // Overflow scrolls (in a clipping scroll view) instead of shrinking
        // icons below the minimum; otherwise the items sit in the bar itself.
        this._setOverflow(fit.overflow, fit.itemsLength);

        this._geometry = geometry;
        this._place();
    }

    _setOverflow(overflow, itemsLength) {
        const inScroll = this._box.get_parent() === this._scroll;
        if (overflow && !inScroll) {
            this._dock.remove_child(this._box);
            this._scroll.set_child(this._box);
        } else if (!overflow && inScroll) {
            this._scroll.set_child(null);
            this._dock.insert_child_above(this._box, this._searchButton);
        }
        this._scroll.visible = overflow;
        if (overflow) {
            this._scroll.set_policy(
                this._vertical ? St.PolicyType.NEVER : St.PolicyType.AUTOMATIC,
                this._vertical ? St.PolicyType.AUTOMATIC : St.PolicyType.NEVER);
            if (this._vertical)
                this._scroll.set_size(-1, itemsLength);
            else
                this._scroll.set_size(itemsLength, -1);
        }
        this._overflow = overflow;
    }

    // -- hover: magnification and labels ------------------------------------

    _magnify(hovered) {
        const on = this._settings.get_boolean('magnify');
        const items = this._box.get_children();
        const at = items.indexOf(hovered);
        items.forEach((item, i) => {
            const distance = at < 0 || !on ? Infinity : Math.abs(i - at);
            item.setMagnification(distance < MAGNIFY.length ? MAGNIFY[distance] : 1);
        });
    }

    _showLabel(actor, text) {
        this._hideLabel();
        this._labelTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, LABEL_DELAY, () => {
            this._labelTimeout = 0;
            if (!actor.hover || this._previews.isOpen || this._menuOpen)
                return GLib.SOURCE_REMOVE;
            this._label.text = text;
            this._label.show();
            const [x, y] = actor.get_transformed_position();
            const [w, h] = actor.get_transformed_size();
            const [, lw] = this._label.get_preferred_width(-1);
            const [, lh] = this._label.get_preferred_height(lw);
            // Above the magnified icon at the bottom, beside it on the sides.
            const lift = h * (MAGNIFY[0] - 1);
            const pos = {
                bottom: [x + w / 2 - lw / 2, y - lh - 8 - lift],
                left: [x + w + 8 + w * (MAGNIFY[0] - 1), y + h / 2 - lh / 2],
                right: [x - lw - 8 - w * (MAGNIFY[0] - 1), y + h / 2 - lh / 2],
            }[this._position];
            this._label.set_position(Math.round(pos[0]), Math.round(pos[1]));
            return GLib.SOURCE_REMOVE;
        });
    }

    _hideLabel() {
        if (this._labelTimeout) {
            GLib.source_remove(this._labelTimeout);
            this._labelTimeout = 0;
        }
        this._label.hide();
    }

    _onButtonHover(button, text) {
        if (button.hover)
            this._showLabel(button, text);
        else
            this._hideLabel();
    }

    // Positions the container around the dock's natural size. Measured on
    // the dock box, never on the container, whose size this method sets.
    _place() {
        if (this._destroyed || !this._geometry)
            return;
        const [, natW] = this._dock.get_preferred_width(-1);
        const [, natH] = this._dock.get_preferred_height(natW);
        const rect = this._geometry.place(natW, natH);
        const same = this._rect && ['x', 'y', 'width', 'height'].every(k => this._rect[k] === rect[k]);
        this._rect = rect;
        if (!same) {
            this.set_position(rect.x, rect.y);
            this.set_size(rect.width, rect.height);
            const edge = this._geometry.edgeStrip(rect);
            this._edge.set_position(edge.x, edge.y);
            this._edge.set_size(edge.width, edge.height);
            this._hiddenOffset = this._geometry.hiddenOffset(rect);
            if (!this._shown) {
                this.translation_x = this._hiddenOffset.x;
                this.translation_y = this._hiddenOffset.y;
            }
        }
        this._sync();
    }

    // Styles apply after the first measurement, and items change size, so
    // re-place whenever the dock's allocation changes (before the next frame).
    _queuePlace() {
        if (this._placeLater || this._destroyed)
            return;
        this._placeLater = global.compositor.get_laters().add(Meta.LaterType.BEFORE_REDRAW, () => {
            this._placeLater = 0;
            this._place();
            return GLib.SOURCE_REMOVE;
        });
    }

    // -- visibility -------------------------------------------------------

    _queueSync() {
        if (this._syncTimeout)
            return;
        this._syncTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            this._syncTimeout = 0;
            this._sync();
            return GLib.SOURCE_REMOVE;
        });
    }

    _keyboardInside() {
        const focus = global.stage.key_focus;
        return Boolean(focus && this._dock.contains(focus));
    }

    _overlapsWindow() {
        if (!this._rect)
            return false;
        const workspace = global.workspace_manager.get_active_workspace();
        for (const actor of global.get_window_actors()) {
            const win = actor.meta_window;
            if (!win || win.minimized || !win.showing_on_its_workspace())
                continue;
            if (win.get_window_type() === Meta.WindowType.DESKTOP)
                continue;
            if (!win.located_on_workspace(workspace))
                continue;
            const f = win.get_frame_rect();
            if (f.x < this._rect.x + this._rect.width && f.x + f.width > this._rect.x &&
                f.y < this._rect.y + this._rect.height && f.y + f.height > this._rect.y) {
                this._lastOverlap = {title: win.get_title(), rect: [f.x, f.y, f.width, f.height]};
                return true;
            }
        }
        this._lastOverlap = null;
        return false;
    }

    wantsVisible() {
        if (Main.overview.visible || Main.overview.animationInProgress)
            return false;
        if (this._behavior === 'always' || this.hover || this._menuOpen || this._previews.isOpen ||
            this._keyboardInside() || this._dragging)
            return true;
        if (this._behavior === 'intellihide')
            return !this._overlapsWindow();
        return false; // autohide
    }

    _sync() {
        if (this._destroyed)
            return;
        if (this.wantsVisible()) {
            this._clearHideTimeout();
            this._show();
        } else if (Main.overview.visible) {
            this._hide(true);
        } else if (this._shown && !this._hideTimeout) {
            this._hideTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, HIDE_DELAY, () => {
                this._hideTimeout = 0;
                if (!this.wantsVisible())
                    this._hide(false);
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _clearHideTimeout() {
        if (this._hideTimeout) {
            GLib.source_remove(this._hideTimeout);
            this._hideTimeout = 0;
        }
    }

    _reveal() {
        if (Main.overview.visible)
            return;
        this._show();
        this._sync(); // schedules the hide again unless the pointer stays
    }

    _animationTime() {
        return St.Settings.get().enable_animations ? SHOW_TIME : 0;
    }

    _show() {
        this.visible = true;
        this._edge.visible = false;
        if (this._shown)
            return;
        this._shown = true;
        this.reactive = true;
        this.ease({
            translation_x: 0,
            translation_y: 0,
            opacity: 255,
            duration: this._animationTime(),
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _hide(immediate) {
        this._clearHideTimeout();
        this._previews.close();
        this._edge.visible = !Main.overview.visible;
        if (!this._shown)
            return;
        this._shown = false;
        this.reactive = false;
        this.ease({
            translation_x: this._hiddenOffset?.x ?? 0,
            translation_y: this._hiddenOffset?.y ?? 0,
            opacity: 0,
            duration: immediate ? 0 : this._animationTime(),
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (!this._shown)
                    this.visible = false;
            },
        });
    }

    // -- previews ---------------------------------------------------------

    _onItemHover(item) {
        if (this._previewTimeout) {
            GLib.source_remove(this._previewTimeout);
            this._previewTimeout = 0;
        }
        const hovered = this._box.get_children().find(i => i.hover) ?? null;
        this._magnify(hovered);
        if (!item.hover) {
            if (!hovered)
                this._hideLabel();
            this._previews.scheduleClose();
            return;
        }
        this._showLabel(item, item.app.get_name());
        if (this._menuOpen || !this._settings.get_boolean('show-previews') || item.app.get_n_windows() === 0)
            return;
        this._previewTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PREVIEW_DELAY, () => {
            this._previewTimeout = 0;
            if (item.hover && !this._menuOpen) {
                this._hideLabel(); // the previews carry the window titles
                this._previews.open(item);
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    // -- drag and drop (pinning and reordering favorites) -----------------

    handleDragOver(source) {
        const app = source?.app;
        if (!app || app.is_window_backed())
            return DND.DragMotionResult.NO_DROP;
        this._dragging = true;
        return DND.DragMotionResult.MOVE_DROP;
    }

    acceptDrop(source, actor, x, y) {
        this._dragging = false;
        const app = source?.app;
        if (!app || app.is_window_backed())
            return false;
        const centers = this._box.get_children().slice(0, this._favoriteCount).map(child => {
            const box = child.get_allocation_box();
            return this._vertical ? (box.y1 + box.y2) / 2 : (box.x1 + box.x2) / 2;
        });
        const pos = dropIndex(centers, this._vertical ? y : x);
        const favorites = AppFavorites.getAppFavorites();
        const id = app.get_id();
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (favorites.isFavorite(id))
                favorites.moveFavoriteToPos(id, pos);
            else
                favorites.addFavoriteAtPos(id, pos);
            return GLib.SOURCE_REMOVE;
        });
        return true;
    }

    // -- lifecycle --------------------------------------------------------

    destroy() {
        this._destroyed = true;
        if (this._placeLater)
            global.compositor.get_laters().remove(this._placeLater);
        this._placeLater = 0;
        this.remove_all_transitions();
        this._clearHideTimeout();
        for (const id of ['_previewTimeout', '_syncTimeout']) {
            if (this[id])
                GLib.source_remove(this[id]);
            this[id] = 0;
        }
        for (const actor of global.get_window_actors())
            actor.meta_window?.disconnectObject(this);
        this._previews.destroy();
        this._hideLabel();
        Main.layoutManager.removeChrome(this._label);
        this._label.destroy();
        Main.layoutManager.removeChrome(this._edge);
        this._edge.destroy();
        Main.layoutManager.removeChrome(this);
        super.destroy();
    }

    debugState() {
        const {favorites, running} = this._apps();
        return {
            position: this._position,
            behavior: this._behavior,
            shown: this._shown,
            visible: this.visible,
            iconSize: this._iconSize,
            items: this._box.get_children().map(c => c.app.get_id()),
            itemRects: this._box.get_children().map(c => {
                const [x, y] = c.get_transformed_position();
                const [w, h] = c.get_transformed_size();
                return [x, y, w, h].map(Math.round);
            }),
            overflow: Boolean(this._overflow),
            startButton: this._startButton.visible,
            searchButton: this._searchButton.visible,
            magnification: Object.fromEntries(this._box.get_children().map(c =>
                [c.app.get_id(), Math.round(c.magnification * 100) / 100])),
            label: this._label.visible ? this._label.text : null,
            favorites: favorites.map(a => a.get_id()),
            running: running.map(a => a.get_id()),
            rect: this._rect ? [this._rect.x, this._rect.y, this._rect.width, this._rect.height] : null,
            monitor: (({x, y, width, height}) => [x, y, width, height])(Main.layoutManager.primaryMonitor),
            previewsOpen: this._previews.isOpen,
            hovered: this._box.get_children().filter(c => c.hover).map(c => c.app.get_id()),
            windowCounts: Object.fromEntries(this._box.get_children().map(c =>
                [c.app.get_id(), c.app.get_windows().length])),
            containerHover: this.hover,
            lastOverlap: this._lastOverlap ?? null,
            overlapsNow: this._overlapsWindow(),
            wantsVisible: this.wantsVisible(),
        };
    }
});
