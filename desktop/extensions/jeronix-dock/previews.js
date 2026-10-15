// SPDX-License-Identifier: GPL-3.0-or-later
//
// Window previews for a dock item: live thumbnails (clones of the window
// actors) for windows on the active workspace, titled entries for windows
// elsewhere. Clicking one activates that window, switching workspace if
// needed.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

const MAX_WINDOWS = 6;
const THUMB_WIDTH = 220;
const THUMB_HEIGHT = 140;
const GAP = 10;
const CLOSE_DELAY = 300;

export class WindowPreviews {
    constructor(dock, side) {
        this._dock = dock;
        this._side = side;
        this._actor = null;
        this._item = null;
        this._closeTimeout = 0;
    }

    get isOpen() {
        return this._actor !== null;
    }

    _windows(app) {
        return app.get_windows().filter(w => !w.skip_taskbar).slice(0, MAX_WINDOWS);
    }

    open(item) {
        this.close();
        const windows = this._windows(item.app);
        if (windows.length === 0)
            return;

        const box = new St.BoxLayout({
            style_class: 'jeronix-dock-previews',
            orientation: this._side === St.Side.BOTTOM
                ? Clutter.Orientation.HORIZONTAL : Clutter.Orientation.VERTICAL,
            reactive: true,
            track_hover: true,
        });
        const workspace = global.workspace_manager.get_active_workspace();
        for (const win of windows)
            box.add_child(this._preview(win, win.located_on_workspace(workspace)));
        box.connect('notify::hover', () => (box.hover ? this._cancelClose() : this.scheduleClose()));

        Main.layoutManager.addTopChrome(box);
        this._actor = box;
        this._item = item;
        this._place();
    }

    _preview(win, live) {
        const content = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL});
        const actor = win.get_compositor_private();
        if (live && actor) {
            const [w, h] = actor.get_size();
            const scale = Math.min(THUMB_WIDTH / w, THUMB_HEIGHT / h, 1);
            const clone = new Clutter.Clone({
                source: actor,
                width: Math.round(w * scale),
                height: Math.round(h * scale),
            });
            content.add_child(new St.Bin({style_class: 'jeronix-dock-preview-thumb', child: clone}));
        }
        const title = win.get_title() || win.get_wm_class() || '';
        content.add_child(new St.Label({
            text: live ? title : `${title} — ${_('Workspace %d').format(win.get_workspace().index() + 1)}`,
            style_class: 'jeronix-dock-preview-title',
        }));
        const button = new St.Button({
            style_class: 'jeronix-dock-preview',
            can_focus: true,
            accessible_name: title,
            child: content,
        });
        button.connect('clicked', () => {
            Main.activateWindow(win);
            this.close();
        });
        return button;
    }

    _place() {
        const [ix, iy] = this._item.get_transformed_position();
        const [iw, ih] = this._item.get_transformed_size();
        const [, bw] = this._actor.get_preferred_width(-1);
        const [, bh] = this._actor.get_preferred_height(bw);
        const m = Main.layoutManager.primaryMonitor;
        let x, y;
        if (this._side === St.Side.BOTTOM) {
            x = ix + iw / 2 - bw / 2;
            y = iy - bh - GAP;
        } else if (this._side === St.Side.LEFT) {
            x = ix + iw + GAP;
            y = iy + ih / 2 - bh / 2;
        } else {
            x = ix - bw - GAP;
            y = iy + ih / 2 - bh / 2;
        }
        x = Math.max(m.x + GAP, Math.min(x, m.x + m.width - bw - GAP));
        y = Math.max(m.y + GAP, Math.min(y, m.y + m.height - bh - GAP));
        this._actor.set_position(Math.round(x), Math.round(y));
    }

    _cancelClose() {
        if (this._closeTimeout) {
            GLib.source_remove(this._closeTimeout);
            this._closeTimeout = 0;
        }
    }

    scheduleClose() {
        if (!this._actor || this._closeTimeout)
            return;
        this._closeTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, CLOSE_DELAY, () => {
            this._closeTimeout = 0;
            if (this._actor && !this._actor.hover && !this._item?.hover)
                this.close();
            return GLib.SOURCE_REMOVE;
        });
    }

    close() {
        this._cancelClose();
        if (!this._actor)
            return;
        Main.layoutManager.removeChrome(this._actor);
        this._actor.destroy();
        this._actor = null;
        this._item = null;
        this._dock._queueSync();
    }

    destroy() {
        this._cancelClose();
        if (this._actor) {
            Main.layoutManager.removeChrome(this._actor);
            this._actor.destroy();
            this._actor = null;
        }
    }
}
