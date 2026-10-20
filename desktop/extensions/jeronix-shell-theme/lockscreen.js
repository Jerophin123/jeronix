// SPDX-License-Identifier: GPL-3.0-or-later
//
// The JERONIX lock screen. GNOME's look is stripped from the lock screen and
// replaced by JERONIX's own:
//
//  * the wallpaper is shown sharp while locked, and blurs only as the
//    password prompt comes up (GNOME blurs it all the time);
//  * a large JERONIX clock and date high on the screen, and a quiet hint at
//    the bottom, instead of GNOME's clock;
//  * no notification list, no media player, and no top bar until the prompt
//    is shown (the top bar then offers the keyboard layout, accessibility and
//    power menus, which someone may need to log in).
//
// Authentication stays entirely GNOME's: the password prompt, PAM,
// fingerprint and smart card handling, and every key and swipe that leads
// to them are untouched. This module only changes what is drawn around them.
//
// It adapts GNOME's own unlock dialog each time one is created. The dialog
// is checked for the parts this relies on first; on any other GNOME
// version, it is left exactly as GNOME made it.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GnomeDesktop from 'gi://GnomeDesktop';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Layout from 'resource:///org/gnome/shell/ui/layout.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {formatDateWithCFormatString} from 'resource:///org/gnome/shell/misc/dateUtils.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

// GNOME's own blur (js/ui/unlockDialog.js) is reached on the prompt page.
const PROMPT_BLUR_RADIUS = 90;
const PROMPT_BRIGHTNESS = 0.65;
// The clock page: the wallpaper itself, slightly dimmed for the white text.
const CLOCK_BRIGHTNESS = 0.82;
// Where the clock sits, as a fraction of the screen height from the top.
const CLOCK_POSITION = 0.17;

function warn(message, error) {
    console.warn(`JERONIX lock screen: ${message}${error ? `: ${error.message ?? error}` : ''}`);
}

/** Whether dialog has every part of GNOME 50's unlock dialog used here. */
function isUnlockDialog(dialog) {
    return Boolean(dialog?.has_style_class_name?.('unlock-dialog') && dialog._adjustment instanceof St.Adjustment &&
        dialog._clock instanceof St.Widget && dialog._notificationsBox instanceof St.Widget &&
        dialog._backgroundGroup instanceof Clutter.Actor);
}

/** The JERONIX clock page: time, date and hint, over the sharp wallpaper. */
class LockView {
    constructor() {
        // Clock high on the screen, hint at the bottom: a spacer of a share of
        // the screen height, the clock, a flexible spacer, the hint.
        this.actor = new St.BoxLayout({
            style_class: 'jeronix-lock',
            orientation: Clutter.Orientation.VERTICAL,
            reactive: false,
        });
        this.actor.add_constraint(new Layout.MonitorConstraint({primary: true}));
        this._column = new St.BoxLayout({
            style_class: 'jeronix-lock-clock',
            orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._time = new St.Label({style_class: 'jeronix-lock-time', x_align: Clutter.ActorAlign.CENTER});
        this._date = new St.Label({style_class: 'jeronix-lock-date', x_align: Clutter.ActorAlign.CENTER});
        this._column.add_child(this._time);
        this._column.add_child(this._date);
        this._top = new St.Widget();  // pushes the clock down (see _place)
        this.actor.add_child(this._top);
        this.actor.add_child(this._column);
        this.actor.add_child(new St.Widget({y_expand: true}));
        this._hint = new St.Label({
            style_class: 'jeronix-lock-hint',
            text: _('Press a key or click to unlock'),
            x_align: Clutter.ActorAlign.CENTER,
        });
        this.actor.add_child(this._hint);

        // The same clock GNOME uses: follows the 12/24-hour setting.
        this._wallClock = new GnomeDesktop.WallClock({time_only: true});
        this._wallClock.connect('notify::clock', () => this._update());
        // The clock's place follows the primary monitor (the view's size
        // comes from a constraint, which emits no size notifications).
        Main.layoutManager.connectObject('monitors-changed', () => this._place(), this);
        this._place();
        this._update();
    }

    _place() {
        const height = Main.layoutManager.primaryMonitor?.height ?? 0;
        this._top.height = Math.round(height * CLOCK_POSITION);
    }

    _update() {
        this._time.text = this._wallClock.clock.trim();
        // GNOME's own long date format, translated for the session language.
        this._date.text = formatDateWithCFormatString(new Date(), Shell.util_translate_time_string('%A, %B %-d'));
    }

    get state() {
        const rect = a => {
            const [x, y] = a.get_transformed_position();
            const [w, h] = a.get_transformed_size();
            return [x, y, w, h].map(Math.round);
        };
        return {time: this._time.text, date: this._date.text, opacity: this.actor.opacity,
            rect: rect(this.actor), clock: rect(this._column), hint: rect(this._hint)};
    }

    destroy() {
        Main.layoutManager.disconnectObject(this);
        this._wallClock.run_dispose();
        this.actor.destroy();
    }
}

export class LockScreen {
    constructor() {
        this._group = Main.screenShield?._lockDialogGroup ?? null;
        this._dialog = null;
        if (!(this._group instanceof Clutter.Actor)) {
            warn("GNOME's lock screen is not where JERONIX expects it; keeping GNOME's");
            this._group = null;
            return;
        }
        // GNOME creates a new unlock dialog every time the screen locks. It
        // adds itself to the group at the start of its constructor, so it is
        // adopted once construction has finished.
        this._pending = 0;
        this._group.connectObject('child-added', () => this._queueAdopt(), this);
        this._queueAdopt();
    }

    _queueAdopt() {
        if (this._pending)
            return;
        this._pending = GLib.idle_add(GLib.PRIORITY_HIGH_IDLE, () => {
            this._pending = 0;
            for (const child of this._group?.get_children() ?? [])
                this._adopt(child);
            return GLib.SOURCE_REMOVE;
        });
    }

    _adopt(dialog) {
        if (dialog === this._dialog || !dialog?.has_style_class_name?.('unlock-dialog'))
            return;
        if (!isUnlockDialog(dialog)) {
            warn('unexpected unlock dialog; keeping GNOME\'s lock screen');
            return;
        }
        this._release();
        try {
            this._dialog = dialog;
            this._view = new LockView();
            // Above the backgrounds, below GNOME's prompt and buttons.
            dialog.insert_child_above(this._view.actor, dialog._backgroundGroup);
            for (const child of dialog._clock.get_children())
                child.hide();
            dialog._notificationsBox.hide();
            dialog._notificationsBox.connectObject('notify::visible', box => {
                if (box.visible)
                    box.hide();
            }, this);
            dialog._adjustment.connectObject('notify::value', () => this._sync(), this);
            dialog._backgroundGroup.connectObject('child-added', () => this._sync(), this);
            dialog.connectObject('destroy', () => this._release(true), this);
            this._sync();
        } catch (e) {
            warn('could not adapt the lock screen; restoring GNOME\'s', e);
            this._release();
        }
    }

    /** Follows GNOME's page transition: 0 is the clock, 1 the prompt. */
    _sync() {
        const dialog = this._dialog;
        if (!dialog)
            return;
        const progress = Math.min(1, Math.max(0, dialog._adjustment.value));
        this._view.actor.opacity = Math.round(255 * (1 - progress));
        const {scaleFactor} = St.ThemeContext.get_for_stage(global.stage);
        for (const widget of dialog._backgroundGroup) {
            widget.get_effect('blur')?.set({
                radius: PROMPT_BLUR_RADIUS * scaleFactor * progress,
                brightness: CLOCK_BRIGHTNESS + (PROMPT_BRIGHTNESS - CLOCK_BRIGHTNESS) * progress,
            });
        }
        // The top bar appears with the prompt (keyboard layout, accessibility, power).
        Main.panel.opacity = Math.round(255 * progress);
        Main.panel.reactive = progress > 0.5;
    }

    /** Gives the dialog (if it still exists) and the top bar back to GNOME. */
    _release(destroyed = false) {
        const dialog = this._dialog;
        this._dialog = null;
        Main.panel.opacity = 255;
        Main.panel.reactive = true;
        if (!dialog)
            return;
        dialog._adjustment?.disconnectObject(this);
        dialog._backgroundGroup?.disconnectObject(this);
        dialog._notificationsBox?.disconnectObject(this);
        dialog.disconnectObject(this);
        if (!destroyed) {
            for (const child of dialog._clock.get_children())
                child.show();
            dialog._notificationsBox._updateVisibility?.();
            dialog._updateBackgroundEffects?.();
        }
        this._view?.destroy();
        this._view = null;
    }

    // Read-only state for tests.
    debugState() {
        return {
            adopted: Boolean(this._dialog),
            view: this._view?.state ?? null,
            gnomeClockShown: this._dialog ? this._dialog._clock.get_children().some(c => c.visible) : null,
            notificationsShown: this._dialog ? this._dialog._notificationsBox.visible : null,
            panelOpacity: Main.panel.opacity,
        };
    }

    destroy() {
        if (this._pending)
            GLib.source_remove(this._pending);
        this._pending = 0;
        this._release();
        this._group?.disconnectObject(this);
        this._group = null;
    }
}
