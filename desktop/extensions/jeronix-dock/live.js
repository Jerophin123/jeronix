// SPDX-License-Identifier: GPL-3.0-or-later
//
// Live updates: the free left end of the taskbar (where Windows 11 shows
// its weather) shows what is going on, as an icon with two short lines, and
// opens the widgets.
//
//  * Ongoing activities: a screen recording (time, stop), the microphone or
//    camera in use (and by which apps), a low battery (Power Saver), timers
//    and focus sessions (time left, pause, stop), music (play/pause),
//    downloads (name, size), Stay Awake.
//  * Glimpses, for a moment over everything: a volume or brightness change,
//    a new notification, a timer done, the charger plugged in or out, the
//    network connected or lost, a finished download, Caps Lock.
//  * With several ongoing, a "+N" count shows how many more; scrolling over
//    the area cycles through them, and the widgets list them all.
//  * Otherwise: waiting notifications, the weather (with GNOME Weather set
//    up), or "Widgets".
//
// A click opens the widgets panel (or, on a glimpse that has one, its
// action: open the notification, the download). The panel lists the
// ongoing activities with their controls, then the widgets chosen and
// ordered in JERONIX Settings ('live-widgets'); which activities show is
// chosen there too ('live-activities'). Which activity shows when is
// decided by live-model.js; everything here is wiring to public Shell and
// D-Bus interfaces, each of which can be missing without breaking the rest.

import Clutter from 'gi://Clutter';
import GdkPixbuf from 'gi://GdkPixbuf';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GnomeDesktop from 'gi://GnomeDesktop';
import GObject from 'gi://GObject';
import Gvc from 'gi://Gvc';
import NM from 'gi://NM';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Keyboard from 'resource:///org/gnome/shell/ui/status/keyboard.js';
import * as Volume from 'resource:///org/gnome/shell/ui/status/volume.js';
import {formatDateWithCFormatString} from 'resource:///org/gnome/shell/misc/dateUtils.js';
import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import {openSettings} from './control-center.js';
import {ACCENTS, ACTIVITY_GROUPS, Activities, ClocksTracker, Countdown, FOCUS_MINUTES, GLIMPSE_MS, PAUSED_MS,
    TIMER_MINUTES, allowedKinds, bytes, cpuTimes, cpuUsage, dominantColor, elapsed, memory, microphoneUsers, monthGrid, networkChange,
    notificationCount, partialDownload, remainingText, tintFor, tintStyle, widgetList} from './live-model.js';

const WIDGETS_KEY = 'live-widgets';
const ACTIVITIES_KEY = 'live-activities';
const COLORS_KEY = 'live-colors';
const EXPAND_KEY = 'live-expand';
// Hovering this long expands the live updates (as the Dynamic Island does
// when pressed); leaving for this long brings them back.
const EXPAND_DELAY_MS = 250;
const COLLAPSE_DELAY_MS = 400;
const MORPH_MS = 260;
const POP_MS = 360;
// Below this, on battery, the battery becomes an ongoing activity.
const LOW_BATTERY_PERCENT = 15;
const STAY_AWAKE_UUID = 'jeronix-quick-settings@jeronix';
const MPRIS_PREFIX = 'org.mpris.MediaPlayer2.';
const MPRIS_PATH = '/org/mpris/MediaPlayer2';
const MPRIS_PLAYER = 'org.mpris.MediaPlayer2.Player';
const SYSTEM_REFRESH_MS = 2000;
const FADE_MS = 220;
// Levels read while starting up (login, a taskbar rebuild) are not changes.
const QUIET_START_MS = 3000;

function warn(message, error) {
    console.warn(`JERONIX live updates: ${message}${error ? `: ${error.message ?? error}` : ''}`);
}

function readText(path) {
    try {
        const [ok, bytesRead] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytesRead) : '';
    } catch {
        return '';
    }
}

function icon(name, styleClass = 'jeronix-live-icon') {
    return new St.Icon({
        gicon: typeof name === 'string' ? Gio.ThemedIcon.new(name) : name,
        style_class: styleClass,
        y_align: Clutter.ActorAlign.CENTER,
    });
}

function label(text, styleClass) {
    return new St.Label({text: text ?? '', style_class: styleClass, y_align: Clutter.ActorAlign.CENTER});
}

/** A thin level bar (0..1) for volume, brightness and the system widget. */
function levelBar(value, styleClass = 'jeronix-live-bar') {
    const track = new LevelTrack({style_class: styleClass, y_align: Clutter.ActorAlign.CENTER, x_expand: true});
    track.fill.style_class = `${styleClass}-fill`;
    track.setValue(value);
    return track;
}

/**
 * The track of a level bar. Its size comes from its style alone (the fill
 * never widens it, so what holds it can shrink), and the fill is placed at
 * its left edge, as wide as the value: never centered.
 */
const LevelTrack = GObject.registerClass(
class JeronixLevelTrack extends St.Widget {
    _init(params) {
        super._init(params);
        this._value = 0;
        this.fill = new St.Widget();
        this.add_child(this.fill);
    }

    setValue(value) {
        const v = Math.min(1, Math.max(0, Number(value) || 0));
        if (v !== this._value) {
            this._value = v;
            this.queue_relayout();
        }
    }

    vfunc_get_preferred_width(forHeight) {
        return this.get_theme_node().adjust_preferred_width(0, 0);
    }

    vfunc_get_preferred_height(forWidth) {
        return this.get_theme_node().adjust_preferred_height(0, 0);
    }

    vfunc_allocate(box) {
        this.set_allocation(box);
        const content = this.get_theme_node().get_content_box(box);
        const fill = new Clutter.ActorBox();
        fill.x1 = content.x1;
        fill.y1 = content.y1;
        fill.x2 = content.x1 + Math.round((content.x2 - content.x1) * this._value);
        fill.y2 = content.y2;
        this.fill.allocate(fill);
    }
});

/**
 * What makes a view look different, beyond its texts: its activity, icon,
 * buttons and extra count. Views with the same shape are updated in place,
 * so a button is never replaced under the pointer by a ticking timer.
 */
function viewShape(id, kind, view, buttons, more = 0) {
    const iconKey = view.icon instanceof St.Icon ? view.icon.gicon?.to_string() ?? '' : 'dot';
    const names = buttons.map(b => b.accessible_name).join(',');
    return `${id}|${kind}|${iconKey}|${names}|${more}|${typeof view.detail}|${view.icon.style_class ?? ''}` +
        `|${view.progress !== undefined}`;
}

/** Every button of a view, compact and expanded, once each. */
function viewButtons(view) {
    return [...new Set([...view.buttons ?? [], ...view.expandedButtons ?? []])];
}

/** Destroys the actors of a view that was only needed for its texts. */
function discardView(view) {
    view.icon.destroy();
    for (const button of viewButtons(view))
        button.destroy();
    if (typeof view.detail !== 'string')
        view.detail.destroy();
}

// -- live sources ------------------------------------------------------------------------
//
// Each source reports to the live updates through set(id, kind, data, durationMs)
// and remove(id), and cleans up after itself in destroy().

class RecordingSource {
    constructor(live) {
        this._live = live;
        this._ui = Main.screenshotUI ?? null;
        this._ui?.connectObject('notify::screencast-in-progress', () => this._sync(), this);
        this._sync();
    }

    _sync() {
        const recording = Boolean(this._ui?.screencast_in_progress);
        if (recording && !this._started) {
            this._started = GLib.get_monotonic_time();
            this._tick = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
                this._update();
                return GLib.SOURCE_CONTINUE;
            });
        } else if (!recording && this._started) {
            this._stopTimer();
            this._live.remove('recording');
        }
        if (recording)
            this._update();
    }

    _update() {
        const seconds = (GLib.get_monotonic_time() - this._started) / 1e6;
        this._live.set('recording', 'recording', {time: elapsed(seconds), stop: () => this.stop()});
    }

    sync() {
        this._sync();
    }

    stop() {
        this._ui?.stopScreencast?.().catch?.(e => warn('cannot stop the recording', e));
    }

    _stopTimer() {
        if (this._tick)
            GLib.source_remove(this._tick);
        this._tick = 0;
        this._started = 0;
    }

    destroy() {
        this._stopTimer();
        this._ui?.disconnectObject(this);
    }
}

/** Volume and brightness changes, from wherever they come (keys, sliders). */
class LevelSource {
    constructor(live) {
        this._live = live;
        this._quietUntil = GLib.get_monotonic_time() + QUIET_START_MS * 1000;
        this._control = Volume.getMixerControl();
        this._control.connectObject(
            'state-changed', () => this._bindSink(),
            'default-sink-changed', () => this._bindSink(),
            'default-source-changed', () => this._bindSource(),
            this);
        this._control.connectObject('state-changed', () => this._bindSource(), this);
        this._bindSink();
        this._bindSource();
        this._brightness = Main.brightnessManager ?? null;
        this._brightness?.connectObject('changed', () => this._bindBrightness(), this);
        this._bindBrightness();
    }

    _bindSink() {
        const stream = this._control.get_state() === Gvc.MixerControlState.READY
            ? this._control.get_default_sink() : null;
        if (stream === this._stream)
            return;
        this._stream?.disconnectObject(this);
        this._stream = stream;
        // A new default device is not a volume change: no glimpse for it.
        stream?.connectObject(
            'notify::volume', () => this._volume(),
            'notify::is-muted', () => this._volume(),
            this);
    }

    /** The microphone muted or unmuted (a glimpse, as a phone shows it). */
    _bindSource() {
        const stream = this._control.get_state() === Gvc.MixerControlState.READY
            ? this._control.get_default_source() : null;
        if (stream === this._source)
            return;
        this._source?.disconnectObject(this);
        this._source = stream;
        this._micMuted = stream?.is_muted ?? null;
        stream?.connectObject('notify::is-muted', () => {
            if (stream.is_muted === this._micMuted)
                return;
            this._micMuted = stream.is_muted;
            if (this.listening)
                this._live.set('mic', 'mic', {muted: stream.is_muted}, GLIMPSE_MS.mic);
        }, this);
    }

    /** Whether level changes show yet (not in the first moments after starting). */
    get listening() {
        return GLib.get_monotonic_time() >= this._quietUntil;
    }

    _glimpse(data) {
        if (this.listening)
            this._live.set('level', 'level', data, GLIMPSE_MS.level);
    }

    _volume() {
        const s = this._stream;
        if (!s)
            return;
        const value = s.is_muted ? 0 : s.volume / this._control.get_vol_max_norm();
        const name = s.is_muted || value === 0 ? 'audio-volume-muted-symbolic'
            : value < 0.34 ? 'audio-volume-low-symbolic'
                : value < 0.67 ? 'audio-volume-medium-symbolic' : 'audio-volume-high-symbolic';
        this._glimpse({icon: name, value, label: _('Volume')});
    }

    _bindBrightness() {
        const scale = this._brightness?.globalScale ?? null;
        if (scale === this._scale)
            return;
        this._scale?.disconnectObject(this);
        this._scale = scale;
        scale?.connectObject('notify::value', () => this._glimpse(
            {icon: 'display-brightness-symbolic', value: scale.value, label: _('Brightness')}), this);
    }

    destroy() {
        this._stream?.disconnectObject(this);
        this._source?.disconnectObject(this);
        this._scale?.disconnectObject(this);
        this._control.disconnectObject(this);
        this._brightness?.disconnectObject(this);
    }
}

/** A glimpse of each new notification, as its banner would show it. */
class NotificationSource {
    constructor(live) {
        this._live = live;
        this._sources = new Set();
        this._banners = new Gio.Settings({schema_id: 'org.gnome.desktop.notifications'});
        const tray = Main.messageTray;
        tray.connectObject('source-added', (t, source) => this._watch(source), this);
        for (const source of tray.getSources?.() ?? [])
            this._watch(source);
    }

    _watch(source) {
        if (this._sources.has(source))
            return;
        this._sources.add(source);
        source.connectObject(
            'notification-request-banner', (s, notification) => this._show(notification),
            'notify::count', () => this._live.refresh(),
            'destroy', () => this._unwatch(source),
            this);
    }

    _unwatch(source) {
        source.disconnectObject(this);
        this._sources.delete(source);
        this._live.refresh();
    }

    /** Notifications waiting in the notification center. */
    get count() {
        let n = 0;
        for (const source of this._sources)
            n += source.count ?? 0;
        return n;
    }

    /** Opens the notification center (GNOME's, wherever it is). */
    openCenter() {
        Main.panel.statusArea.dateMenu?.menu?.open();
    }

    _show(notification) {
        // Do Not Disturb: only critical notifications, as GNOME's banners.
        if (!this._banners.get_boolean('show-banners') && notification.urgency !== MessageTray.Urgency.CRITICAL)
            return;
        const id = 'notification';
        this._live.set(id, 'notification', {
            gicon: notification.gicon ?? notification.source?.icon ?? null,
            title: notification.title || notification.source?.title || _('Notification'),
            body: notification.body ?? '',
            activate: () => {
                try {
                    notification.activate();
                } catch (e) {
                    warn('cannot open the notification', e);
                }
            },
        }, GLIMPSE_MS.notification);
    }

    destroy() {
        for (const source of this._sources)
            source.disconnectObject(this);
        this._sources.clear();
        Main.messageTray.disconnectObject(this);
    }
}

/** The battery as UPower shows it: glimpses when the charger is plugged or unplugged. */
class PowerSource {
    static CHARGING = 1;
    static DISCHARGING = 2;
    static FULL = 4;

    constructor(live, onChanged) {
        this._live = live;
        this._onChanged = onChanged;
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, null, 'org.freedesktop.UPower',
            '/org/freedesktop/UPower/devices/DisplayDevice', 'org.freedesktop.UPower.Device', null, (o, res) => {
                try {
                    this._proxy = Gio.DBusProxy.new_for_bus_finish(res);
                } catch (e) {
                    warn('UPower unavailable', e);
                    return;
                }
                if (this._destroyed)
                    return;
                this._state = this._get('State');
                this._proxy.connectObject('g-properties-changed', () => this._changed(), this);
                this.sync();
                this._onChanged();
            });
    }

    _get(name) {
        return this._proxy?.get_cached_property(name)?.unpack();
    }

    get present() {
        return this._get('IsPresent') === true && this._get('Type') === 2;
    }

    get percentage() {
        return Math.round(this._get('Percentage') ?? 0);
    }

    get charging() {
        return [PowerSource.CHARGING, PowerSource.FULL].includes(this._get('State'));
    }

    get iconName() {
        return this._get('IconName') || 'battery-symbolic';
    }

    _changed() {
        const state = this._get('State');
        const plugged = [PowerSource.CHARGING, PowerSource.FULL];
        if (this.present && state !== this._state && plugged.includes(state) !== plugged.includes(this._state)) {
            this._live.set('power', 'power', {
                icon: this.iconName,
                text: plugged.includes(state) ? _('Charging') : _('On battery'),
                percent: `${this.percentage}%`,
            }, GLIMPSE_MS.power);
        }
        this._state = state;
        this.sync();
        this._onChanged();
    }

    sync() {
        if (this.present && !this.charging && this.percentage <= LOW_BATTERY_PERCENT) {
            const seconds = this._get('TimeToEmpty') ?? 0;
            const minutes = Math.round(seconds / 60);
            this._live.set('battery-low', 'battery-low', {
                percent: `${this.percentage}%`,
                left: minutes > 0 ? (minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min`
                    : `${minutes} min`) : '',
                powerSaver: () => PowerSource.powerSaver(),
            });
        } else {
            this._live.remove('battery-low');
        }
    }

    /** Switches to the Power Saver profile (power-profiles-daemon or tuned-ppd). */
    static powerSaver() {
        const call = (name, path, iface, next) => Gio.DBus.system.call(name, path,
            'org.freedesktop.DBus.Properties', 'Set',
            new GLib.Variant('(ssv)', [iface, 'ActiveProfile', new GLib.Variant('s', 'power-saver')]),
            null, Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch (e) {
                    if (next)
                        next();
                    else
                        warn('cannot turn on Power Saver', e);
                }
            });
        call('org.freedesktop.UPower.PowerProfiles', '/org/freedesktop/UPower/PowerProfiles',
            'org.freedesktop.UPower.PowerProfiles',
            () => call('net.hadess.PowerProfiles', '/net/hadess/PowerProfiles', 'net.hadess.PowerProfiles', null));
    }

    destroy() {
        this._destroyed = true;
        this._proxy?.disconnectObject(this);
        this._proxy = null;
    }
}

/** Media players (MPRIS), followed as they appear, play, pause and quit. */
class MediaSource {
    constructor(live, onChanged) {
        this._live = live;
        this._onChanged = onChanged;
        this._players = new Map();
        this._pausedTimer = 0;
        // A D-Bus namespace match takes the namespace without its final dot.
        this._ownerId = Gio.DBus.session.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus',
            'NameOwnerChanged', '/org/freedesktop/DBus', MPRIS_PREFIX.slice(0, -1),
            Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE, (conn, sender, path, iface, signal, params) => {
                const [name, , owner] = params.deepUnpack();
                if (!name.startsWith(MPRIS_PREFIX))
                    return;
                if (owner)
                    this._add(name);
                else
                    this._remove(name);
            });
        Gio.DBus.session.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames',
            null, new GLib.VariantType('(as)'), Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
                try {
                    const [names] = bus.call_finish(res).deepUnpack();
                    names.filter(n => n.startsWith(MPRIS_PREFIX)).forEach(n => this._add(n));
                } catch (e) {
                    warn('cannot list media players', e);
                }
            });
    }

    _add(name) {
        if (this._destroyed || this._players.has(name))
            return;
        const player = {name, proxy: null};
        this._players.set(name, player);
        Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION, Gio.DBusProxyFlags.GET_INVALIDATED_PROPERTIES, null,
            name, MPRIS_PATH, MPRIS_PLAYER, null, (o, res) => {
                let proxy;
                try {
                    proxy = Gio.DBusProxy.new_for_bus_finish(res);
                } catch (e) {
                    warn(`media player ${name} unavailable`, e);
                    return;
                }
                if (this._destroyed || this._players.get(name) !== player)
                    return;
                player.proxy = proxy;
                proxy.connectObject('g-properties-changed', () => this._sync(), this);
                this._sync();
            });
    }

    _remove(name) {
        const player = this._players.get(name);
        if (!player)
            return;
        player.proxy?.disconnectObject(this);
        this._players.delete(name);
        this._sync();
    }

    static _info(player) {
        const get = prop => player.proxy?.get_cached_property(prop)?.recursiveUnpack();
        const metadata = get('Metadata') ?? {};
        const artists = metadata['xesam:artist'];
        const length = Number(metadata['mpris:length'] ?? 0);
        return {
            length,
            status: get('PlaybackStatus'),
            title: metadata['xesam:title'] || _('Unknown title'),
            artist: Array.isArray(artists) ? artists.join(', ') : artists ?? '',
            art: metadata['mpris:artUrl'] ?? null,
            canNext: get('CanGoNext') !== false,
            canPrevious: get('CanGoPrevious') !== false,
        };
    }

    /** [player, info] of the player to show: playing first, then paused; or null. */
    _pick() {
        const players = [...this._players.values()].filter(p => p.proxy?.g_name_owner);
        const info = players.map(p => [p, MediaSource._info(p)]);
        return info.find(([, i]) => i.status === 'Playing') ?? info.find(([, i]) => i.status === 'Paused') ?? null;
    }

    /** The player to show: playing first, then paused; or null. */
    get current() {
        const pick = this._pick();
        if (!pick)
            return null;
        const [player, i] = pick;
        // How far the song is: players tell their position only when asked.
        const progress = i.length > 0 && !player.noPosition
            ? Math.min(1, Math.max(0, (player.position ?? 0) / i.length)) : undefined;
        const call = method => player.proxy.call(method, null, Gio.DBusCallFlags.NONE, -1, null, (p, res) => {
            try {
                p.call_finish(res);
            } catch (e) {
                warn(`${method} failed`, e);
            }
        });
        return {...i, progress, color: artColor(i.art), playPause: () => call('PlayPause'), next: () => call('Next'),
            previous: () => call('Previous'), raise: () => MediaSource._raise(player.name)};
    }

    /** Brings the player's window up (MPRIS Raise, on the root interface). */
    static _raise(name) {
        Gio.DBus.session.call(name, MPRIS_PATH, 'org.mpris.MediaPlayer2', 'Raise', null, null,
            Gio.DBusCallFlags.NONE, -1, null, (bus, res) => {
                try {
                    bus.call_finish(res);
                } catch (e) {
                    warn('cannot raise the player', e);
                }
            });
    }

    /** Asks the shown player where it is, then shows it. */
    _poll() {
        const [player] = this._pick() ?? [];
        if (!player || player.noPosition)
            return;
        Gio.DBus.session.call(player.name, MPRIS_PATH, 'org.freedesktop.DBus.Properties', 'Get',
            new GLib.Variant('(ss)', [MPRIS_PLAYER, 'Position']), new GLib.VariantType('(v)'),
            Gio.DBusCallFlags.NONE, 1000, null, (bus, res) => {
                try {
                    const [value] = bus.call_finish(res).deepUnpack();
                    player.position = Number(value.deepUnpack());
                } catch {
                    player.noPosition = true; // a player without positions: no progress bar
                }
                if (!this._destroyed)
                    this._sync();
            });
    }

    _syncPolling(media) {
        const wanted = Boolean(media && media.status === 'Playing' && media.progress !== undefined);
        if (wanted && !this._pollTimer) {
            this._pollTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
                this._poll();
                return GLib.SOURCE_CONTINUE;
            });
            this._poll();
        } else if (!wanted && this._pollTimer) {
            GLib.source_remove(this._pollTimer);
            this._pollTimer = 0;
        }
    }

    sync() {
        this._sync();
    }

    _sync() {
        const media = this.current;
        // The panel's cards are rebuilt only when the song or its controls
        // change, not on every position tick: rebuilding them each second
        // replaced the Previous/Next buttons under the pointer, losing clicks.
        const shape = media ? JSON.stringify([media.title, media.artist, media.art, media.status,
            media.canNext, media.canPrevious, media.progress !== undefined]) : '';
        const changed = shape !== this._shape;
        this._shape = shape;
        if (this._pausedTimer) {
            GLib.source_remove(this._pausedTimer);
            this._pausedTimer = 0;
        }
        this._syncPolling(media);
        if (!media) {
            this._live.remove('media');
        } else {
            this._live.set('media', 'media', media);
            // A paused song lingers a little, then the live updates let it go.
            if (media.status !== 'Playing') {
                this._pausedTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PAUSED_MS, () => {
                    this._pausedTimer = 0;
                    this._live.remove('media');
                    return GLib.SOURCE_REMOVE;
                });
            }
        }
        if (changed)
            this._onChanged();
    }

    destroy() {
        this._destroyed = true;
        if (this._pausedTimer)
            GLib.source_remove(this._pausedTimer);
        if (this._pollTimer)
            GLib.source_remove(this._pollTimer);
        this._pollTimer = 0;
        Gio.DBus.session.signal_unsubscribe(this._ownerId);
        for (const player of this._players.values())
            player.proxy?.disconnectObject(this);
        this._players.clear();
    }
}

/** Stay Awake, owned by the jeronix-quick-settings extension (its public API). */
class StayAwakeSource {
    constructor(live) {
        this._live = live;
        Main.extensionManager.connectObject('extension-state-changed', () => this._attach(), this);
        this._attach();
    }

    _attach() {
        const ext = Main.extensionManager.lookup(STAY_AWAKE_UUID)?.stateObj ?? null;
        const usable = ext?.stayAwakeAvailable ? ext : null;
        if (usable !== this._ext) {
            this._unwatch?.();
            this._unwatch = usable ? usable.watchStayAwake(() => this._sync()) : null;
            this._ext = usable;
        }
        this._sync();
    }

    _sync() {
        if (this._ext?.stayAwakeWanted) {
            this._live.set('stay-awake', 'stay-awake', {toggle: () => this._ext?.setStayAwake(false)});
        } else {
            this._live.remove('stay-awake');
        }
    }

    destroy() {
        this._unwatch?.();
        this._unwatch = null;
        Main.extensionManager.disconnectObject(this);
    }
}

// Timers and focus sessions. They are kept here, outside the taskbar, so
// that a running timer survives the taskbar being rebuilt (a setting
// changed); their time comes from the monotonic clock, so they stay exact.
// A focus session turns on Do Not Disturb for its length.
const timers = new Map();
let timerSerial = 0;

function nowMs() {
    return GLib.get_monotonic_time() / 1000;
}

/** Timers and focus sessions, started from the Timer widget. */
class TimerSource {
    constructor(live) {
        this._live = live;
        this._tick = 0;
        this._notifications = new Gio.Settings({schema_id: 'org.gnome.desktop.notifications'});
        this.sync();
    }

    /** Starts a timer of minutes (a focus session if focus); returns its id. */
    start(minutes, focus = false) {
        const id = `timer-${++timerSerial}`;
        timers.set(id, {id, minutes, focus, countdown: new Countdown(minutes * 60000, nowMs())});
        this.sync();
        return id;
    }

    togglePause(id) {
        const t = timers.get(id);
        if (!t)
            return;
        if (t.countdown.paused)
            t.countdown.resume(nowMs());
        else
            t.countdown.pause(nowMs());
        this.sync();
    }

    /** Adds ms to a timer (the "+1 min" button). */
    extend(id, ms) {
        timers.get(id)?.countdown.add(ms, nowMs());
        this.sync();
    }

    cancel(id) {
        if (timers.delete(id)) {
            this._live.remove(id);
            this.sync();
        }
    }

    get list() {
        return [...timers.values()];
    }

    // Do Not Disturb follows the focus sessions: on while one runs (not
    // paused), and back to what it was when the last one ends.
    _syncFocus() {
        const focusing = this.list.some(t => t.focus && !t.countdown.paused);
        const banners = this._notifications;
        if (focusing && TimerSource._bannersBefore === undefined) {
            TimerSource._bannersBefore = banners.get_boolean('show-banners');
            banners.set_boolean('show-banners', false);
        } else if (!focusing && TimerSource._bannersBefore !== undefined) {
            banners.set_boolean('show-banners', TimerSource._bannersBefore);
            TimerSource._bannersBefore = undefined;
        }
    }

    /** Shows every timer, ends those that are done, and ticks while any runs. */
    sync() {
        const now = nowMs();
        for (const t of this.list) {
            if (t.countdown.done(now)) {
                timers.delete(t.id);
                this._live.remove(t.id);
                this._finish(t);
                continue;
            }
            this._live.set(t.id, 'timer', {
                title: t.focus ? _('Focus') : _('Timer'),
                focus: t.focus,
                remaining: remainingText(t.countdown.remaining(now)),
                progress: t.countdown.progress(now),
                paused: t.countdown.paused,
                togglePause: () => this.togglePause(t.id),
                cancel: () => this.cancel(t.id),
                extend: () => this.extend(t.id, 60000),
            });
        }
        this._syncFocus();
        const running = this.list.some(t => !t.countdown.paused);
        if (running && !this._tick) {
            this._tick = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
                this.sync();
                return this._tick ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
            });
        } else if (!running && this._tick) {
            GLib.source_remove(this._tick);
            this._tick = 0;
        }
    }

    _finish(t) {
        const title = t.focus ? _('Focus session done') : _('Timer done');
        const detail = t.focus ? _('Time for a break') : `${t.minutes} min`;
        this._syncFocus(); // Do Not Disturb ends before the alert
        this._live.set(`${t.id}-done`, 'timer-done', {title, detail}, GLIMPSE_MS['timer-done']);
        try {
            global.display.get_sound_player().play_from_theme('complete', title, null);
        } catch (e) {
            warn('cannot play the timer sound', e);
        }
        Main.notify(title, detail);
    }

    destroy() {
        if (this._tick)
            GLib.source_remove(this._tick);
        this._tick = 0;
        // The timers stay (a rebuilt taskbar picks them up), but Do Not
        // Disturb is never left on by a taskbar that is gone.
        if (TimerSource._bannersBefore !== undefined) {
            this._notifications.set_boolean('show-banners', TimerSource._bannersBefore);
            TimerSource._bannersBefore = undefined;
        }
    }
}

const CLOCKS_APP = 'org.gnome.clocks.desktop';
const CLOCKS_READ_MS = 1500; // how often Clocks is read while it is in front
const CLOCKS_SETTLE_MS = 300; // Clocks drawing again after coming to the front

/**
 * GNOME Clocks' stopwatch and timers as live activities. Clocks publishes
 * nothing about them, so a helper process (clocks-probe.js) reads its
 * window over accessibility while Clocks runs: often while it is in front
 * (where every Start, Pause or Reset is pressed), once as it leaves the
 * front, and after each button pressed from here. In between the times
 * count on by themselves (ClocksTracker, live-model.js).
 */
class ClocksSource {
    constructor(live) {
        this._live = live;
        this._tracker = new ClocksTracker();
        this._ids = new Set();
        this._queue = [];
        this._app = Shell.AppSystem.get_default().lookup_app(CLOCKS_APP);
        if (!this._app)
            throw new Error('GNOME Clocks is not installed');
        const schema = Gio.SettingsSchemaSource.get_default()?.lookup('org.gnome.clocks', true);
        this._clocksSettings = schema ? new Gio.Settings({schema_id: 'org.gnome.clocks'}) : null;
        this._probePath = GLib.build_filenamev([
            GLib.path_get_dirname(GLib.filename_from_uri(import.meta.url)[0]), 'clocks-probe.js']);
        this._app.connectObject('notify::state', () => this._appChanged(), this);
        global.display.connectObject('notify::focus-window', () => this._focusChanged(), this);
        this._appChanged();
    }

    get _running() {
        return this._app.state === Shell.AppState.RUNNING;
    }

    get _focused() {
        const window = global.display.focus_window;
        return Boolean(window && Shell.WindowTracker.get_default().get_window_app(window) === this._app);
    }

    _appChanged() {
        if (this._running) {
            this._read();
        } else {
            this._stopProbe();
            this._tracker.clear();
            this._show();
        }
        this._focusChanged();
    }

    _focusChanged() {
        const focused = this._running && this._focused;
        if (focused && !this._readTimer) {
            // Read once Clocks draws again, then often while it stays in front.
            this._readTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, CLOCKS_SETTLE_MS, () => {
                this._read();
                this._readTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, CLOCKS_READ_MS, () => {
                    this._read();
                    return GLib.SOURCE_CONTINUE;
                });
                return GLib.SOURCE_REMOVE;
            });
        } else if (!focused && this._readTimer) {
            GLib.source_remove(this._readTimer);
            this._readTimer = 0;
            if (this._running)
                this._read(); // as it leaves the front
        }
    }

    // -- the helper process ----------------------------------------------------------

    _startProbe() {
        if (this._probe)
            return true;
        try {
            this._probe = Gio.Subprocess.new(['gjs', '-m', this._probePath],
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (e) {
            warn('cannot start the Clocks reader', e);
            this._probe = null;
            return false;
        }
        this._probeIn = new Gio.DataOutputStream({base_stream: this._probe.get_stdin_pipe()});
        this._probeOut = new Gio.DataInputStream({base_stream: this._probe.get_stdout_pipe()});
        return true;
    }

    _stopProbe() {
        this._probe?.force_exit();
        this._probe = null;
        this._probeIn = this._probeOut = null;
        this._busy = false;
        this._queue = [];
    }

    /** Sends a command to the helper; one at a time, the rest wait. */
    _send(command) {
        if (this._busy) {
            // A read waiting already covers another read.
            if (command !== 'read' || !this._queue.includes('read'))
                this._queue.push(command);
            return;
        }
        if (this._gone || !this._running || !this._startProbe())
            return;
        this._busy = true;
        const sent = nowMs();
        const probe = this._probe;
        try {
            this._probeIn.put_string(`${command}\n`, null);
        } catch (e) {
            warn('the Clocks reader stopped', e);
            this._stopProbe();
            return;
        }
        this._probeOut.read_line_async(GLib.PRIORITY_DEFAULT, null, (stream, res) => {
            if (probe !== this._probe || this._gone)
                return; // stopped meanwhile
            let line = null;
            try {
                [line] = stream.read_line_finish_utf8(res);
            } catch (e) {
                warn('cannot read the Clocks reader', e);
            }
            this._busy = false;
            if (line === null) {
                this._stopProbe(); // it ended: started again on the next command
                return;
            }
            // A read happens between sending and answering: take the middle.
            this._took(line, (sent + nowMs()) / 2);
            const next = this._queue.shift();
            if (next)
                this._send(next);
        });
    }

    _read() {
        this._send('read');
    }

    _press(...args) {
        this._send(`press ${args.join(' ')}`);
    }

    _took(line, at) {
        let read;
        try {
            read = JSON.parse(line);
        } catch {
            return;
        }
        if (!read.ok)
            return;
        if (!read.running)
            this._tracker.clear();
        else
            this._tracker.update(read, at, this._durations());
        this._show();
    }

    /** The timers' lengths in seconds, by row, as Clocks keeps them. */
    _durations() {
        try {
            return (this._clocksSettings?.get_value('timers').recursiveUnpack() ?? []).map(t => Number(t.duration) || 0);
        } catch {
            return [];
        }
    }

    // -- the activities ------------------------------------------------------------------

    _show() {
        if (this._gone)
            return;
        const state = this._tracker.state(nowMs());
        const ids = new Set();
        const open = () => this._app.activate();
        if (state.stopwatch) {
            const {seconds, running} = state.stopwatch;
            ids.add('clocks-stopwatch');
            this._live.set('clocks-stopwatch', 'stopwatch', {
                time: elapsed(Math.floor(seconds)), running,
                togglePause: () => this._press('stopwatch', 0),
                second: () => this._press('stopwatch', 1), // Lap, or Clear when paused
                open,
            });
        }
        for (const t of state.timers) {
            const id = `clocks-timer-${t.index}`;
            ids.add(id);
            this._live.set(id, 'timer', {
                title: t.name || _('Timer'),
                remaining: remainingText(t.seconds * 1000),
                progress: t.progress,
                paused: !t.running,
                // Running, a row shows only Pause; paused: Start, Reset, Delete.
                togglePause: () => this._press('timer', t.index, 0),
                cancel: () => {
                    if (t.running)
                        this._press('timer', t.index, 0);
                    this._press('timer', t.index, 1);
                },
                open,
            });
        }
        for (const id of this._ids) {
            if (!ids.has(id))
                this._live.remove(id);
        }
        this._ids = ids;
        // Count on each second while something runs.
        if (this._tracker.active && !this._tick) {
            this._tick = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
                this._show();
                return this._tick ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
            });
        } else if (!this._tracker.active && this._tick) {
            GLib.source_remove(this._tick);
            this._tick = 0;
        }
    }

    sync() {
        if (this._running)
            this._read();
        this._show();
    }

    destroy() {
        this._gone = true;
        this._app.disconnectObject(this);
        global.display.disconnectObject(this);
        for (const timer of [this._readTimer, this._tick].filter(Boolean))
            GLib.source_remove(timer);
        this._readTimer = this._tick = 0;
        this._stopProbe();
        for (const id of this._ids)
            this._live.remove(id);
    }
}

/** Microphone or camera in use, and by which apps (a privacy indicator). */
class PrivacySource {
    constructor(live) {
        this._live = live;
        this._control = Volume.getMixerControl();
        this._control.connectObject(
            'state-changed', () => this.sync(),
            'stream-added', () => this.sync(),
            'stream-removed', () => this.sync(),
            this);
        try {
            this._camera = new Shell.CameraMonitor();
            this._camera.connectObject('notify::cameras-in-use', () => this.sync(), this);
        } catch (e) {
            this._camera = null;
        }
        this.sync();
    }

    sync() {
        const ready = this._control.get_state() === Gvc.MixerControlState.READY;
        const outputs = ready ? this._control.get_source_outputs().map(o => ({
            id: o.get_application_id?.() ?? '', name: o.get_name?.() ?? '',
        })) : [];
        const apps = microphoneUsers(outputs);
        const camera = Boolean(this._camera?.cameras_in_use);
        if (!apps.length && !camera)
            this._live.remove('privacy');
        else
            this._live.set('privacy', 'privacy', {microphone: apps.length > 0, camera, apps});
    }

    destroy() {
        this._control.disconnectObject(this);
        this._camera?.disconnectObject(this);
        this._camera?.run_dispose();
        this._camera = null;
    }
}

/** Downloads, as browsers write them into the Downloads folder. */
class DownloadSource {
    constructor(live) {
        this._live = live;
        this._partials = new Map(); // file name -> Gio.File
        this._tick = 0;
        const path = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) ??
            GLib.build_filenamev([GLib.get_home_dir(), 'Downloads']);
        this._dir = Gio.File.new_for_path(path);
        try {
            this._monitor = this._dir.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, null);
            this._monitor.connect('changed', (m, file, other, event) => this._changed(file, other, event));
        } catch (e) {
            this._monitor = null; // no Downloads folder: nothing to follow
        }
    }

    _changed(file, other, event) {
        const E = Gio.FileMonitorEvent;
        const name = file.get_basename();
        if ([E.CREATED, E.MOVED_IN, E.CHANGES_DONE_HINT].includes(event) && partialDownload(name) !== null) {
            this._partials.set(name, file);
        } else if (event === E.RENAMED && partialDownload(name) !== null) {
            this._partials.delete(name);
            const final = other?.get_basename();
            if (final && partialDownload(final) === null)
                this._finished(other);
            else if (final)
                this._partials.set(final, other);
        } else if ((event === E.DELETED || event === E.MOVED_OUT) && this._partials.delete(name)) {
            // Moved aside without a rename: finished if the final file is there.
            const finalName = partialDownload(name);
            const final = finalName ? this._dir.get_child(finalName) : null;
            if (final?.query_exists(null))
                this._finished(final);
        }
        this.sync();
    }

    _finished(file) {
        this._live.set('downloaded', 'downloaded', {
            name: file.get_basename(),
            openFolder: () => this.openFolder(),
            activate: () => {
                try {
                    Gio.AppInfo.launch_default_for_uri(file.get_uri(), global.create_app_launch_context(0, -1));
                } catch (e) {
                    warn('cannot open the download', e);
                }
            },
        }, GLIMPSE_MS.downloaded);
    }

    openFolder() {
        try {
            Gio.AppInfo.launch_default_for_uri(this._dir.get_uri(), global.create_app_launch_context(0, -1));
        } catch (e) {
            warn('cannot open Downloads', e);
        }
    }

    sync() {
        if (!this._partials.size) {
            this._live.remove('download');
            if (this._tick)
                GLib.source_remove(this._tick);
            this._tick = 0;
            return;
        }
        let size = 0;
        for (const file of this._partials.values()) {
            try {
                size += file.query_info('standard::size', Gio.FileQueryInfoFlags.NONE, null).get_size();
            } catch {
                // gone between two checks: the next event says why
            }
        }
        const [first] = this._partials.keys();
        this._live.set('download', 'download', {
            name: partialDownload(first) || _('A download'),
            count: this._partials.size,
            size: bytes(size),
            openFolder: () => this.openFolder(),
        });
        // Sizes grow without events worth waiting for: look every second.
        this._tick ||= GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
            this.sync();
            return this._tick ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
        });
    }

    destroy() {
        if (this._tick)
            GLib.source_remove(this._tick);
        this._tick = 0;
        this._monitor?.cancel();
        this._monitor = null;
    }
}

/** Network connected, switched or lost. */
class NetworkSource {
    constructor(live) {
        this._live = live;
        this._last = null;
        NM.Client.new_async(null, (o, res) => {
            try {
                this._client = NM.Client.new_finish(res);
            } catch (e) {
                warn('NetworkManager unavailable', e);
                return;
            }
            if (this._destroyed)
                return;
            this._client.connectObject(
                'notify::primary-connection', () => this.sync(),
                'notify::state', () => this.sync(),
                this);
            this.sync();
        });
    }

    sync() {
        const client = this._client;
        if (!client)
            return;
        const c = client.primary_connection;
        const after = {
            connected: Boolean(c) && client.state >= NM.State.CONNECTED_LOCAL,
            name: c?.get_id() ?? '',
            wifi: c?.get_connection_type() === '802-11-wireless',
        };
        const change = networkChange(this._last, after);
        this._last = after;
        if (change) {
            this._live.set('network', 'network', {...change, offline: change.icon === 'network-offline-symbolic'},
                GLIMPSE_MS.network);
        }
    }

    destroy() {
        this._destroyed = true;
        this._client?.disconnectObject(this);
        this._client = null;
    }
}

/** Caps Lock turned on or off. */
class KeyboardSource {
    constructor(live) {
        this._live = live;
        this._keymap = Clutter.get_default_backend().get_default_seat().get_keymap();
        this._caps = this._keymap.get_caps_lock_state();
        this._keymap.connectObject('state-changed', () => {
            const caps = this._keymap.get_caps_lock_state();
            if (caps === this._caps)
                return;
            this._caps = caps;
            this._live.set('keyboard', 'keyboard', {caps}, GLIMPSE_MS.keyboard);
        }, this);
    }

    destroy() {
        this._keymap.disconnectObject(this);
    }
}

/** Do Not Disturb while it is on (a focus session shows itself instead). */
class DndSource {
    constructor(live) {
        this._live = live;
        this._notifications = new Gio.Settings({schema_id: 'org.gnome.desktop.notifications'});
        this._notifications.connectObject('changed::show-banners', () => this.sync(), this);
        this.sync();
    }

    get on() {
        return !this._notifications.get_boolean('show-banners');
    }

    set on(value) {
        this._notifications.set_boolean('show-banners', !value);
    }

    sync() {
        if (this.on && TimerSource._bannersBefore === undefined)
            this._live.set('dnd', 'dnd', {off: () => (this.on = false)});
        else
            this._live.remove('dnd');
    }

    destroy() {
        this._notifications.disconnectObject(this);
    }
}

/** A glimpse of the workspace switched to, with a dot for each. */
class WorkspaceSource {
    constructor(live) {
        this._live = live;
        global.workspace_manager.connectObject('active-workspace-changed', () => {
            const wm = global.workspace_manager;
            const count = wm.get_n_workspaces();
            if (count > 1) {
                this._live.set('workspace', 'workspace', {index: wm.get_active_workspace_index(), count},
                    GLIMPSE_MS.workspace);
            }
        }, this);
    }

    destroy() {
        global.workspace_manager.disconnectObject(this);
    }
}

/** A glimpse of the keyboard layout switched to. */
class InputSourceSource {
    constructor(live) {
        this._live = live;
        this._quietUntil = GLib.get_monotonic_time() + QUIET_START_MS * 1000;
        this._manager = Keyboard.getInputSourceManager();
        this._manager.connectObject('current-source-changed', () => {
            const source = this._manager.currentSource;
            const count = Object.keys(this._manager.inputSources ?? {}).length;
            if (!source || count < 2 || GLib.get_monotonic_time() < this._quietUntil)
                return;
            this._live.set('input-source', 'input-source', {name: source.displayName, short: source.shortName},
                GLIMPSE_MS['input-source']);
        }, this);
    }

    destroy() {
        this._manager.disconnectObject(this);
    }
}

// Album art colors, by URL (a song's art is read once).
const artColors = new Map();

/** The color of a song's album art (a local file), or null. */
function artColor(url) {
    if (!url?.startsWith('file://'))
        return null;
    if (artColors.has(url))
        return artColors.get(url);
    let color = null;
    try {
        const path = Gio.File.new_for_uri(url).get_path();
        const pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 24, 24, false);
        color = dominantColor(pixbuf.get_pixels(), pixbuf.get_width(), pixbuf.get_height(),
            pixbuf.get_rowstride(), pixbuf.get_n_channels());
    } catch {
        // unreadable art: the media color
    }
    if (artColors.size > 64)
        artColors.clear();
    artColors.set(url, color);
    return color;
}

// GNOME Shell's weather client never lets go of what it watches, so one is
// made per Shell session, the first time it is needed, and then shared.
let weatherClient;
async function sharedWeather() {
    if (weatherClient === undefined) {
        try {
            const {WeatherClient} = await import('resource:///org/gnome/shell/misc/weather.js');
            weatherClient = new WeatherClient();
        } catch (e) {
            warn('weather unavailable', e);
            weatherClient = null;
        }
    }
    return weatherClient;
}

// -- the live updates area ------------------------------------------------------------------

export class LiveUpdates {
    /**
     * @param {Gio.Settings} settings - the dock extension's settings
     * @param {St.Side} side - which side of the area the taskbar's edge is
     * @param {Function} onMenuState - called with true/false as the widgets open and close
     * @param {Function} anchorRect - optional: given the widgets menu, returns
     *   {x, y, width, height}, the spot (stage coordinates) the panel opens
     *   from; by default just above this area, starting at its left edge
     * @param {Function} room - optional: the widest the area may grow to
     *   (expanded), in pixels; unlimited by default
     */
    constructor(settings, side, onMenuState, anchorRect = null, room = null) {
        this._settings = settings;
        this._side = side;
        this._room = room ?? (() => Infinity);
        this._activities = new Activities();
        this._timer = 0;
        this._hoverTimer = 0;
        this._shown = null;
        this._expanded = false;
        this._allowed = allowedKinds(settings.get_strv(ACTIVITIES_KEY));
        settings.connectObject(`changed::${ACTIVITIES_KEY}`, () => this._activitiesChanged(), this);
        // Colors and expanding follow the settings live (an older schema
        // without them: dynamic colors, expanding on).
        const has = key => settings.settings_schema.has_key(key);
        this._readOptions = () => {
            this._colorMode = has(COLORS_KEY) ? settings.get_string(COLORS_KEY) : 'dynamic';
            this._expandOnHover = has(EXPAND_KEY) ? settings.get_boolean(EXPAND_KEY) : true;
        };
        this._readOptions();
        for (const key of [COLORS_KEY, EXPAND_KEY].filter(has)) {
            settings.connectObject(`changed::${key}`, () => {
                this._readOptions();
                if (!this._expandOnHover)
                    this._collapse();
                this._render();
            }, this);
        }
        try {
            this._interface = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
            if (this._interface.settings_schema.has_key('accent-color'))
                this._interface.connectObject('changed::accent-color', () => this._applyTint(), this);
            else
                this._interface = null;
        } catch {
            this._interface = null;
        }

        this.actor = new St.Button({
            style_class: 'jeronix-live',
            can_focus: true,
            track_hover: true,
            accessible_name: _('Live updates and widgets'),
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: false,
            // Its content stays inside while it grows and shrinks.
            clip_to_allocation: true,
        });
        this._content = new St.BoxLayout({style_class: 'jeronix-live-content', y_align: Clutter.ActorAlign.CENTER,
            x_expand: true});
        this.actor.set_child(this._content);
        this.actor.set_pivot_point(0.5, 0.5);
        // Rendered before the taskbar is on screen, the controls could not be
        // fitted to its room: fit them as soon as it is shown.
        this.actor.connect('notify::mapped', () => {
            if (this.actor.mapped && this._fitPending && !this._gone) {
                this._shape = null;
                this._render();
            }
        });
        this.actor.connect('clicked', () => this._clicked());
        // Scrolling over the area cycles through the ongoing activities.
        this.actor.connect('scroll-event', (actor, event) => this._scrolled(event));
        // Hovering expands it, with more controls (the Dynamic Island).
        this.actor.connect('notify::hover', () => this._hoverChanged());
        // Right click, the Menu key or Shift+F10: options.
        this.actor.connect('button-press-event', (actor, event) => {
            if (event.get_button() !== Clutter.BUTTON_SECONDARY)
                return Clutter.EVENT_PROPAGATE;
            this.toggleOptions();
            return Clutter.EVENT_STOP;
        });
        this.actor.connect('popup-menu', () => this.toggleOptions());

        this.panel = new WidgetsPanel(anchorRect ?? (menu => this._defaultAnchor(menu)), side, settings, this);
        this._reportMenus = () => onMenuState(this.panel.isOpen || Boolean(this._options?.isOpen));
        this.panel.menu.connect('open-state-changed', (m, open) => {
            if (open)
                this._collapse();
            this._reportMenus();
        });

        this._sources = [];
        const add = (Source, ...args) => {
            try {
                const source = new Source(this, ...args);
                this._sources.push(source);
                return source;
            } catch (e) {
                warn(`${Source.name} unavailable`, e);
                return null;
            }
        };
        for (const Source of [RecordingSource, LevelSource, StayAwakeSource, PrivacySource, NetworkSource,
            KeyboardSource, WorkspaceSource, InputSourceSource])
            add(Source);
        this.dnd = add(DndSource);
        this.notifications = add(NotificationSource);
        this.timers = add(TimerSource);
        add(ClocksSource); // GNOME Clocks' stopwatch and timers
        this.downloads = add(DownloadSource);
        this.power = add(PowerSource, () => this.panel.refresh());
        this.media = add(MediaSource, () => this.panel.refresh());
        this._weather = null;
        sharedWeather().then(client => {
            if (this._gone || !client)
                return;
            this._weather = client;
            this._weatherId = client.connect('changed', () => {
                this._render();
                this.panel.refresh();
            });
            this._render();
        });
        this._render();
    }

    _defaultAnchor(menu) {
        const [x, y] = this.actor.get_transformed_position();
        const [, panelWidth] = menu.actor.get_preferred_width(-1);
        return {x: x + panelWidth / 2, y, width: 1, height: 1};
    }

    get weather() {
        return this._weather;
    }

    // -- activities (called by the sources) ---------------------------------

    set(id, kind, data, durationMs = null) {
        if (this._gone)
            return;
        if (!this._allowed.has(kind)) { // turned off in Settings
            this.remove(id);
            return;
        }
        this._activities.set(id, kind, data, GLib.get_monotonic_time() / 1000, durationMs);
        this._render();
        this.panel.refreshActivities();
    }

    remove(id) {
        if (!this._gone && this._activities.remove(id)) {
            this._render();
            this.panel.refreshActivities();
        }
    }

    /** Redraws after something the idle glance shows changed. */
    refresh() {
        if (!this._gone) {
            this._render();
            this.panel.refreshActivities();
        }
    }

    /** Ongoing activities, most important first, for the Activities card. */
    get ongoing() {
        return this._activities.ongoing(GLib.get_monotonic_time() / 1000);
    }

    _activitiesChanged() {
        this._allowed = allowedKinds(this._settings.get_strv(ACTIVITIES_KEY));
        const now = GLib.get_monotonic_time() / 1000;
        for (const item of this._activities.ongoing(now)) {
            if (!this._allowed.has(item.kind))
                this._activities.remove(item.id);
        }
        // Kinds switched back on: every source reports what it knows again.
        for (const source of this._sources)
            source.sync?.();
        this.refresh();
    }

    _scrolled(event) {
        // Every scroll arrives twice: as it really happened (wheel notches,
        // or a touchpad's smooth deltas) and emulated in the other form.
        // Only the real one counts, or one notch would step twice.
        if (event.is_pointer_emulated())
            return Clutter.EVENT_STOP;
        const direction = event.get_scroll_direction();
        let step = 0;
        if (direction === Clutter.ScrollDirection.SMOOTH) {
            // Touchpads: add up the deltas, one step per notch's worth.
            const [dx, dy] = event.get_scroll_delta();
            this._scrollSum = (this._scrollSum ?? 0) + (Math.abs(dy) >= Math.abs(dx) ? dy : dx);
            if (Math.abs(this._scrollSum) >= 1) {
                step = Math.sign(this._scrollSum);
                this._scrollSum = 0;
            }
        } else {
            step = {
                [Clutter.ScrollDirection.DOWN]: 1, [Clutter.ScrollDirection.RIGHT]: 1,
                [Clutter.ScrollDirection.UP]: -1, [Clutter.ScrollDirection.LEFT]: -1,
            }[direction] ?? 0;
        }
        if (step)
            this.cycle(step);
        return Clutter.EVENT_STOP;
    }

    /** Shows the next (1) or previous (-1) ongoing activity. */
    cycle(step) {
        const now = GLib.get_monotonic_time() / 1000;
        this._activities.cycle(step, now);
        this._dismissGlimpses(now);
        this._render();
        this.panel.refreshActivities();
    }

    /** Shows ongoing activity id here (chosen in the widgets panel). */
    show(id) {
        if (this._activities.show(id)) {
            this._dismissGlimpses(GLib.get_monotonic_time() / 1000);
            this._render();
            this.panel.refreshActivities();
        }
    }

    /** A glimpse covering the pill would hide the switch the user just made. */
    _dismissGlimpses(now) {
        const shown = this._activities.current(now);
        if (shown && shown.expires !== null)
            this._activities.remove(shown.id);
    }

    get shownId() {
        return this._shown?.id ?? null;
    }

    _render() {
        if (this._gone)
            return;
        const now = GLib.get_monotonic_time() / 1000;
        const current = this._activities.current(now);
        this._schedule(this._activities.nextChange(now));
        const kind = current?.kind ?? 'idle';
        const changed = this._shown?.id !== current?.id;
        this._shown = current;
        const view = this._view(kind, current?.data ?? {});
        this._glance = view.glance ?? null;
        // How many more things are going on than the one shown.
        const ongoing = this._activities.ongoing(now).length;
        this._more = Math.max(0, current && current.expires === null ? ongoing - 1 : ongoing);
        this.actor.accessible_name = `${view.title}, ${view.spoken ?? view.detail}` +
            (this._more ? `, ${this._more} more` : '');
        // Expanded: the compact controls first, in their places, then more.
        const buttons = this._expanded && view.expandedButtons ? view.expandedButtons : view.buttons ?? [];
        const shape = `${viewShape(current?.id ?? 'idle', kind, view, buttons, this._more)}|${this._expanded}`;
        if (shape === this._shape && typeof view.detail === 'string') {
            // Same activity, same controls: only its texts change (a timer
            // ticking), so nothing under the pointer is replaced.
            this._titleLabel.text = view.title ?? '';
            this._detailLabel.text = view.detail ?? '';
            this._progress?.setValue(view.progress ?? 0);
            discardView(view);
            this._applyTint();
            return;
        }
        this._shape = shape;
        // The width it had, to grow or shrink from (the island's morph).
        this.actor.remove_transition('width');
        const before = this.actor.mapped ? this.actor.width : 0;
        this.actor.set_width(-1);
        this.actor.style_class = `jeronix-live jeronix-live-${kind}${this._expanded ? ' jeronix-live-expanded' : ''}`;
        this._content.destroy_all_children();
        for (const button of viewButtons(view).filter(b => !buttons.includes(b)))
            button.destroy();
        this._content.add_child(view.icon);
        this._icon = view.icon;
        // The text takes any width the pill is given beyond its own (a module
        // expanded toward its panel), so the controls stay at the far end.
        const text = new St.BoxLayout({style_class: 'jeronix-live-text', orientation: Clutter.Orientation.VERTICAL,
            y_align: Clutter.ActorAlign.CENTER, x_expand: true});
        this._titleLabel = label(view.title, 'jeronix-live-title');
        text.add_child(this._titleLabel);
        this._detailLabel = typeof view.detail === 'string' ? label(view.detail, 'jeronix-live-detail') : null;
        text.add_child(this._detailLabel ?? view.detail);
        // How far along (a song, a timer), as the Now Bar shows it.
        this._progress = view.progress !== undefined ? levelBar(view.progress, 'jeronix-live-progress') : null;
        if (this._progress)
            text.add_child(this._progress);
        this._content.add_child(text);
        for (const button of buttons)
            this._content.add_child(button);
        this._moreButton = null;
        if (this._more > 0) {
            // "+N": a click shows the next activity (scrolling cycles too).
            const more = this._moreButton = new St.Button({style_class: 'jeronix-live-more', label: `+${this._more}`, can_focus: true,
                accessible_name: _('Show the next activity'), y_align: Clutter.ActorAlign.CENTER});
            more.connect('clicked', () => this.cycle(1));
            this._content.add_child(more);
        }
        // Expanded only as far as the taskbar has room: extra controls go
        // first, last one first.
        const compact = new Set(view.buttons ?? []);
        // Groups of extras, dropped together (Previous and Next as a pair).
        const groups = (view.dropFirst ?? buttons.filter(b => !compact.has(b)).reverse().map(b => [b]))
            .map(g => g.filter(b => buttons.includes(b) && !compact.has(b))).filter(g => g.length);
        // Sizes are only known on the stage (St styles nothing off it):
        // before the taskbar is shown, fit once it is (see the constructor).
        this._fitPending = !this.actor.get_stage();
        while (!this._fitPending && groups.length && this.actor.get_preferred_width(-1)[1] > this._room())
            groups.shift().forEach(b => b.destroy());
        if (view.icon.has_style_class_name('jeronix-live-dot'))
            this._pulse(view.icon);
        this._applyTint();
        this._morph(before);
        if (changed) {
            // A new update fades in where the last one was; a glimpse pops.
            this._content.opacity = 0;
            this._content.ease({opacity: 255, duration: FADE_MS, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
            if (current?.expires !== null && current?.expires !== undefined)
                this._pop();
        }
    }

    // -- the island: colors, expanding, motion --------------------------------

    _animated() {
        return St.Settings.get().enable_animations && this.actor.mapped;
    }

    /** Grows or shrinks from width before to the new natural width. */
    _morph(before) {
        if (!this._animated() || before < 1)
            return; // not shown: nothing to animate (and nothing to measure)
        const [, after] = this.actor.get_preferred_width(-1);
        if (Math.abs(after - before) < 2)
            return;
        this.actor.width = before;
        this.actor.ease({
            width: after,
            duration: MORPH_MS,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this.actor.set_width(-1),
        });
    }

    /** A glimpse arriving: a small pop, as the Dynamic Island does. */
    _pop() {
        if (!this._animated())
            return;
        this.actor.remove_transition('scale-x');
        this.actor.remove_transition('scale-y');
        this.actor.set_scale(0.92, 0.92);
        this.actor.ease({scale_x: 1, scale_y: 1, duration: POP_MS, mode: Clutter.AnimationMode.EASE_OUT_BACK});
    }

    /** The recording dot breathes while it records. */
    _pulse(dot) {
        if (!St.Settings.get().enable_animations)
            return;
        dot.ease({opacity: 70, duration: 900, mode: Clutter.AnimationMode.EASE_IN_OUT_SINE,
            repeatCount: -1, autoReverse: true});
    }

    _accent() {
        return ACCENTS[this._interface?.get_string('accent-color')] ?? ACCENTS.blue;
    }

    /** The color of what is shown now (live-colors), a little stronger under the pointer. */
    get tint() {
        const kind = this._shown?.kind ?? 'idle';
        const data = kind === 'idle' ? {glance: this._glance} : this._shown.data;
        return tintFor(kind, data, this._colorMode, this._accent());
    }

    _applyTint() {
        if (this._gone)
            return;
        const rgb = this.tint;
        const style = tintStyle(rgb, this.actor.hover ? 1.4 : 1) || null;
        if (style !== this._tintStyle) {
            this._tintStyle = style;
            this.actor.set_style(style);
        }
        // Symbolic icons and the progress take the color; pictures (album
        // art, app icons) keep theirs.
        const color = rgb ? `rgb(${rgb.map(Math.round).join(', ')})` : null;
        if (this._icon instanceof St.Icon && this._icon.style_class === 'jeronix-live-icon')
            this._icon.set_style(color ? `color: ${color};` : null);
        this._progress?.fill.set_style(color ? `background-color: ${color};` : null);
    }

    _hoverChanged() {
        this._applyTint();
        if (this._hoverTimer)
            GLib.source_remove(this._hoverTimer);
        this._hoverTimer = 0;
        if (this._wantsExpanded() === this._expanded)
            return;
        this._hoverTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT,
            this._expanded ? COLLAPSE_DELAY_MS : EXPAND_DELAY_MS, () => {
                this._hoverTimer = 0;
                const wanted = this._wantsExpanded();
                if (wanted !== this._expanded) {
                    this._expanded = wanted;
                    this._render();
                }
                return GLib.SOURCE_REMOVE;
            });
    }

    _wantsExpanded() {
        return this.actor.hover && this._expandOnHover && !this.panel.isOpen && !this._options?.isOpen;
    }

    _collapse() {
        if (this._hoverTimer)
            GLib.source_remove(this._hoverTimer);
        this._hoverTimer = 0;
        if (this._expanded) {
            this._expanded = false;
            this._render();
        }
    }

    get expanded() {
        return this._expanded;
    }

    // -- options (right click) --------------------------------------------------

    /** Opens or closes the options menu. */
    toggleOptions() {
        if (!this._options) {
            const menu = new PopupMenu.PopupMenu(this.actor, 0.1, this._side);
            menu.actor.add_style_class_name('jeronix-live-options');
            Main.uiGroup.add_child(menu.actor);
            menu.actor.hide();
            this._optionsManager = new PopupMenu.PopupMenuManager(this.actor);
            this._optionsManager.addMenu(menu);
            menu.connect('open-state-changed', (m, open) => {
                if (open)
                    this._collapse();
                this._reportMenus();
            });
            this._options = menu;
        }
        if (!this._options.isOpen)
            this._fillOptions();
        this._options.toggle();
    }

    _fillOptions() {
        const menu = this._options;
        menu.removeAll();
        const later = fn => GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (!this._gone)
                fn();
            return GLib.SOURCE_REMOVE;
        });
        if (this.dnd) {
            const dnd = new PopupMenu.PopupSwitchMenuItem(_('Do Not Disturb'), this.dnd.on);
            dnd.connect('toggled', (item, on) => (this.dnd.on = on));
            menu.addMenuItem(dnd);
        }
        const has = key => this._settings.settings_schema.has_key(key);
        if (has(EXPAND_KEY)) {
            const expand = new PopupMenu.PopupSwitchMenuItem(_('Expand on hover'), this._expandOnHover);
            expand.connect('toggled', (item, on) => this._settings.set_boolean(EXPAND_KEY, on));
            menu.addMenuItem(expand);
        }
        if (has(COLORS_KEY)) {
            const colors = new PopupMenu.PopupSubMenuMenuItem(_('Colors'));
            for (const [mode, title] of [['dynamic', _('Follow what is going on')], ['accent', _('Accent color')],
                ['neutral', _('No color')]]) {
                const item = colors.menu.addAction(title, () => this._settings.set_string(COLORS_KEY, mode));
                item.setOrnament(mode === this._colorMode ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
            }
            menu.addMenuItem(colors);
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        // Turning off what is shown now, without going to Settings.
        const kind = this._shown?.kind;
        const group = kind ? Object.keys(ACTIVITY_GROUPS).find(g => ACTIVITY_GROUPS[g].includes(kind)) : null;
        if (group) {
            menu.addAction(_('Stop showing updates like this'), () => this._settings.set_strv(ACTIVITIES_KEY,
                this._settings.get_strv(ACTIVITIES_KEY).filter(id => id !== group)));
        }
        menu.addAction(_('Widgets'), () => later(() => this.panel.toggle()));
        menu.addAction(_('Live Updates Settings'), () => openSettings('desktop'));
    }

    /** What to show for an update: {icon, title, detail, button, spoken}. */
    _view(kind, d) {
        const playing = d.status === 'Playing';
        switch (kind) {
        case 'recording':
            return {
                icon: new St.Widget({style_class: 'jeronix-live-dot', y_align: Clutter.ActorAlign.CENTER}),
                title: _('Recording'), detail: d.time,
                buttons: [this._button('media-playback-stop-symbolic', _('Stop recording'), d.stop)],
            };
        case 'mic':
            return {
                icon: icon(d.muted ? 'microphone-disabled-symbolic' : 'audio-input-microphone-symbolic'),
                title: d.muted ? _('Microphone off') : _('Microphone on'),
                detail: d.muted ? _('Apps cannot hear you') : _('Apps can hear you'),
            };
        case 'workspace': {
            const dots = new St.BoxLayout({style_class: 'jeronix-live-dots', y_align: Clutter.ActorAlign.CENTER});
            for (let i = 0; i < d.count; i++) {
                dots.add_child(new St.Widget({style_class: i === d.index
                    ? 'jeronix-live-page jeronix-live-page-active' : 'jeronix-live-page'}));
            }
            return {icon: icon('focus-windows-symbolic'), title: `${_('Workspace')} ${d.index + 1}`,
                detail: dots, spoken: `${d.index + 1} / ${d.count}`};
        }
        case 'input-source':
            return {icon: icon('input-keyboard-symbolic'), title: d.name || d.short, detail: _('Keyboard layout')};
        case 'dnd': {
            const off = this._button('preferences-system-notifications-symbolic', _('Turn off Do Not Disturb'), d.off);
            return {icon: icon('notifications-disabled-symbolic'), title: _('Do Not Disturb'),
                detail: _('Notifications are silenced'), buttons: [], expandedButtons: [off]};
        }
        case 'privacy': {
            const what = d.camera && d.microphone ? _('Camera and microphone in use')
                : d.camera ? _('Camera in use') : _('Microphone in use');
            return {
                icon: icon(d.camera ? 'camera-web-symbolic' : 'audio-input-microphone-symbolic',
                    'jeronix-live-icon jeronix-live-privacy'),
                title: what, detail: d.apps.length ? d.apps.join(', ') : _('By an app'),
            };
        }
        case 'battery-low':
            return {
                icon: icon('battery-caution-symbolic', 'jeronix-live-icon jeronix-live-warning'),
                title: _('Battery low'), detail: d.left ? `${d.percent} · ${d.left} left` : d.percent,
                buttons: [this._button('power-profile-power-saver-symbolic', _('Power Saver'), d.powerSaver)],
            };
        case 'timer': {
            const buttons = [
                this._button(d.paused ? 'media-playback-start-symbolic' : 'media-playback-pause-symbolic',
                    d.paused ? _('Resume') : _('Pause'), d.togglePause),
                this._button('media-playback-stop-symbolic', _('Stop'), d.cancel),
            ];
            const more = [];
            if (d.extend)
                more.push(this._button('list-add-symbolic', _('Add a minute'), d.extend));
            if (d.open) // a Clocks timer: its app is one click away
                more.push(this._button('view-restore-symbolic', _('Open Clocks'), d.open));
            return {
                icon: icon(d.focus ? 'weather-clear-night-symbolic' : 'alarm-symbolic'),
                title: d.title, detail: d.paused ? `${d.remaining} · ${_('Paused')}` : d.remaining,
                progress: d.progress, buttons, expandedButtons: [...buttons, ...more],
            };
        }
        case 'stopwatch': {
            // GNOME Clocks' stopwatch: Pause or Resume, and Lap (Reset when paused).
            const buttons = [this._button(d.running ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic',
                d.running ? _('Pause') : _('Resume'), d.togglePause)];
            const second = d.running
                ? this._button(Gio.ThemedIcon.new_from_names(['flag-symbolic', 'mail-flag-symbolic',
                    'emoji-flags-symbolic']), _('Lap'), d.second)
                : this._button('edit-undo-symbolic', _('Reset'), d.second);
            return {
                icon: icon(Gio.ThemedIcon.new_from_names(['stopwatch-symbolic', 'org.gnome.clocks-symbolic',
                    'alarm-symbolic'])),
                title: _('Stopwatch'), detail: d.running ? d.time : `${d.time} · ${_('Paused')}`,
                buttons, expandedButtons: [...buttons, second,
                    this._button('view-restore-symbolic', _('Open Clocks'), d.open)],
            };
        }
        case 'timer-done':
            return {icon: icon('alarm-symbolic'), title: d.title, detail: d.detail};
        case 'download':
            return {
                icon: icon('folder-download-symbolic'),
                title: d.count > 1 ? `${_('Downloading')} (${d.count})` : _('Downloading'),
                detail: `${d.name} · ${d.size}`,
                buttons: [], expandedButtons: [this._button('folder-open-symbolic', _('Open Downloads'), d.openFolder)],
            };
        case 'downloaded':
            return {icon: icon('folder-download-symbolic'), title: _('Downloaded'), detail: d.name,
                buttons: [], expandedButtons: [this._button('folder-open-symbolic', _('Show in Downloads'),
                    d.openFolder)]};
        case 'network':
            return {icon: icon(d.icon), title: d.text, detail: d.detail};
        case 'keyboard':
            return {
                icon: icon('input-keyboard-symbolic'),
                title: d.caps ? _('Caps Lock on') : _('Caps Lock off'),
                detail: d.caps ? _('Typing in capitals') : _('Typing normally'),
            };
        case 'level': {
            const percent = `${Math.round(d.value * 100)}%`;
            const row = new St.BoxLayout({style_class: 'jeronix-live-level', y_align: Clutter.ActorAlign.CENTER});
            const bar = levelBar(d.value);
            bar.x_expand = true;
            row.add_child(bar);
            row.add_child(label(percent, 'jeronix-live-detail'));
            return {icon: icon(d.icon), title: d.label, detail: row, spoken: percent};
        }
        case 'notification':
            return {
                icon: d.gicon ? icon(d.gicon, 'jeronix-live-app-icon')
                    : icon('preferences-system-notifications-symbolic'),
                title: d.title, detail: (d.body ?? '').split('\n')[0] || _('New notification'),
                buttons: [], expandedButtons: [this._button('window-close-symbolic', _('Dismiss'),
                    () => this.remove('notification'))],
            };
        case 'power':
            return {icon: icon(d.icon), title: d.text, detail: d.percent};
        case 'media': {
            const play = this._button(playing ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic',
                playing ? _('Pause') : _('Play'), d.playPause);
            // Transport controls in the usual order: Previous, Play, Next.
            const previous = d.canPrevious
                ? this._button('media-skip-backward-symbolic', _('Previous'), d.previous) : null;
            const next = d.canNext ? this._button('media-skip-forward-symbolic', _('Next'), d.next) : null;
            const raise = this._button('view-restore-symbolic', _('Show the player'), d.raise);
            const transport = [previous, play, next].filter(Boolean);
            return {
                icon: icon(this._artIcon(d.art), 'jeronix-live-art'),
                title: d.title, detail: d.artist || (playing ? _('Playing') : _('Paused')),
                progress: d.progress, buttons: [play], expandedButtons: [...transport, raise],
                // Trimmed first when the taskbar is short of room.
                dropFirst: [[raise], [previous, next].filter(Boolean)],
            };
        }
        case 'stay-awake':
            return {icon: icon('view-reveal-symbolic'), title: _('Stay Awake'), detail: _('Screen stays on'),
                buttons: [], expandedButtons: [this._button('window-close-symbolic', _('Turn off Stay Awake'),
                    d.toggle)]};
        default: {
            // Nothing going on: what is most useful to know at a glance.
            // Expanded, it offers quick actions, as the Now Bar does.
            const quick = () => {
                const actions = [];
                if (this.timers) {
                    actions.push(this._button('alarm-symbolic', _('5-minute timer'), () => this.timers.start(5)),
                        this._button('weather-clear-night-symbolic', _('Focus session'),
                            () => this.timers.start(FOCUS_MINUTES, true)));
                }
                if (this.dnd && !this.dnd.on) {
                    actions.push(this._button('notifications-disabled-symbolic', _('Do Not Disturb'),
                        () => (this.dnd.on = true)));
                }
                return actions;
            };
            const waiting = this.notifications?.count ?? 0;
            if (waiting > 0 && this._allowed.has('notification')) {
                return {icon: icon('preferences-system-notifications-symbolic'), glance: 'waiting',
                    title: notificationCount(waiting), detail: _('In the notification center'),
                    buttons: [], expandedButtons: quick()};
            }
            const w = this._weather;
            if (w?.available && w.hasLocation && w.info?.is_valid?.()) {
                return {
                    icon: icon(w.info.get_symbolic_icon_name()), glance: 'weather',
                    title: w.info.get_temp_summary(),
                    detail: w.info.get_sky?.() || w.info.get_location_name?.() || _('Weather'),
                    buttons: [], expandedButtons: quick(),
                };
            }
            return {icon: icon('view-grid-symbolic'), title: _('Widgets'),
                detail: _('Calendar, music and system'), buttons: [], expandedButtons: quick()};
        }
        }
    }

    _artIcon(url) {
        if (url && url.startsWith('file://'))
            return new Gio.FileIcon({file: Gio.File.new_for_uri(url)});
        return Gio.ThemedIcon.new('audio-x-generic-symbolic');
    }

    _button(iconName, accessibleName, callback) {
        const button = new St.Button({style_class: 'jeronix-live-button', can_focus: true,
            accessible_name: accessibleName, child: icon(iconName), y_align: Clutter.ActorAlign.CENTER});
        button.connect('clicked', () => {
            callback?.();
            return Clutter.EVENT_STOP;
        });
        return button;
    }

    _schedule(ms) {
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        if (ms !== null) {
            this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.max(1, Math.ceil(ms)), () => {
                this._timer = 0;
                this._render();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _clicked() {
        // A glimpse with an action (a notification, a finished download)
        // does it, as a banner would.
        if (this._shown && this._shown.expires !== null && this._shown.data.activate) {
            this._shown.data.activate();
            this._activities.remove(this._shown.id);
            this._render();
            return;
        }
        this.panel.toggle();
    }

    _labels(actor) {
        if (actor instanceof St.Label)
            return [actor.text];
        if (actor instanceof St.Button && actor.label)
            return [actor.label]; // a text button ("+1")
        return actor.get_children().flatMap(c => this._labels(c));
    }

    _buttonState() {
        return this._buttonsState()[0] ?? null;
    }

    _buttonsState() {
        return this._content.get_children().filter(c => c instanceof St.Button && c !== this._moreButton).map(button => {
            const [x, y] = button.get_transformed_position();
            const [w, h] = button.get_transformed_size();
            return {name: button.accessible_name, rect: [x, y, w, h].map(Math.round)};
        });
    }

    debugState() {
        return {
            kind: this._shown?.kind ?? 'idle',
            id: this._shown?.id ?? null,
            labels: this._labels(this._content),
            button: this._buttonState(),
            buttons: this._buttonsState(),
            more: this._more ?? 0,
            ongoing: this.ongoing.map(i => i.id),
            pinned: this._activities.pinned,
            panelOpen: this.panel.isOpen,
            panel: this.panel.debugState(),
            levelsShown: this._sources.some(source => source instanceof LevelSource && source.listening),
            expanded: this._expanded,
            tint: this.tint,
            colors: this._colorMode,
            optionsOpen: Boolean(this._options?.isOpen),
            widgets: this.panel.shownWidgets,
        };
    }

    destroy() {
        this._gone = true;
        this._settings.disconnectObject(this);
        this._interface?.disconnectObject(this);
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        if (this._hoverTimer)
            GLib.source_remove(this._hoverTimer);
        this._hoverTimer = 0;
        this._options?.destroy();
        this._options = null;
        if (this._weatherId)
            this._weather.disconnect(this._weatherId);
        this._weatherId = 0;
        for (const source of this._sources)
            source.destroy();
        this._sources = [];
        this.panel.destroy();
        this.actor.destroy();
    }
}

// -- the widgets panel -------------------------------------------------------------------

class WidgetsPanel {
    constructor(anchorRect, side, settings, live) {
        this._settings = settings;
        this._live = live;
        this._anchorRect = anchorRect;
        // An invisible actor the panel opens from, placed before each opening
        // (the panel is centered on it), as for the Start menu.
        this._anchor = new St.Widget({name: 'jeronixWidgetsAnchor', opacity: 0, reactive: false});
        Main.layoutManager.uiGroup.add_child(this._anchor);
        this.menu = new PopupMenu.PopupMenu(this._anchor, 0.5, side);
        this.menu.actor.add_style_class_name('jeronix-widgets-menu');
        Main.uiGroup.add_child(this.menu.actor);
        this.menu.actor.hide();
        this._manager = new PopupMenu.PopupMenuManager(this._anchor);
        this._manager.addMenu(this.menu);

        const scroll = new St.ScrollView({style_class: 'jeronix-widgets-scroll', hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC, overlay_scrollbars: false});
        this._box = new St.BoxLayout({style_class: 'jeronix-widgets', orientation: Clutter.Orientation.VERTICAL});
        scroll.set_child(this._box);
        this.menu.box.add_child(scroll);
        // What is going on, with its controls, above the widgets.
        this._activitiesBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL});
        this._widgetsBox = new St.BoxLayout({style_class: 'jeronix-widgets-list',
            orientation: Clutter.Orientation.VERTICAL});
        this._box.add_child(this._activitiesBox);
        this._box.add_child(this._widgetsBox);
        this._rows = new Map(); // activity id -> {actor, shape, title, detail, progress, buttons}
        this._timerButtons = [];
        this._mediaShown = false; // the Now Playing card is up (music is not listed twice)
        this._mediaProgress = null;
        this.shownWidgets = [];

        this._clock = new GnomeDesktop.WallClock({time_only: true});
        this._clock.connect('notify::clock', () => this.isOpen && this.refresh());
        settings.connectObject(`changed::${WIDGETS_KEY}`, () => this.refresh(), this);
        this.menu.connect('open-state-changed', (m, open) => {
            if (open) {
                this._cpu = null;
                this.refresh();
                this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, SYSTEM_REFRESH_MS, () => {
                    this._refreshSystem();
                    return GLib.SOURCE_CONTINUE;
                });
            } else if (this._timer) {
                GLib.source_remove(this._timer);
                this._timer = 0;
            }
        });
    }

    get isOpen() {
        return this.menu.isOpen;
    }

    toggle() {
        if (!this.isOpen) {
            const {x, y, width, height} = this._anchorRect(this.menu);
            this._anchor.set_position(Math.round(x), Math.round(y));
            this._anchor.set_size(Math.max(1, Math.round(width)), Math.max(1, Math.round(height)));
        }
        this.menu.toggle();
    }

    /** Rebuilds the cards (only while open: nothing runs while closed). */
    refresh() {
        if (!this.isOpen)
            return;
        this._widgetsBox.destroy_all_children();
        this._system = null;
        this._timerButtons = [];
        this.shownWidgets = [];
        this._mediaShown = false;
        this._mediaProgress = null;
        for (const id of widgetList(this._settings.get_strv(WIDGETS_KEY))) {
            const card = this[`_${id}Card`]?.();
            if (card) {
                this._widgetsBox.add_child(card);
                this.shownWidgets.push(id);
            }
        }
        if (!this.shownWidgets.length) {
            const hint = _('Choose widgets in Settings → Desktop & Taskbar.');
            this._widgetsBox.add_child(this._card(_('No widgets'), [label(hint, 'jeronix-widget-muted')]));
        }
        this.refreshActivities();
        this._refreshSystem();
    }

    /**
     * The Activities card: every ongoing activity with its controls, and
     * the notifications waiting. Rows are updated in place while their
     * shape stays the same (a timer ticking), and rebuilt only when it
     * changes, so a button is never replaced under the pointer.
     */
    refreshActivities() {
        if (!this.isOpen)
            return;
        this._syncMediaProgress();
        // Music has its own Now Playing card when that widget is shown: not twice.
        const items = this._live.ongoing.filter(i => !(i.kind === 'media' && this._mediaShown));
        const waiting = this._live.notifications?.count ?? 0;
        for (const [id, row] of this._rows) {
            if (!items.some(i => i.id === id)) {
                row.actor.destroy();
                this._rows.delete(id);
            }
        }
        if (!items.length && !waiting) {
            this._activitiesBox.destroy_all_children();
            this._activitiesCard = null;
            this._rows.clear();
            return;
        }
        if (!this._activitiesCard) {
            this._rowsBox = new St.BoxLayout({style_class: 'jeronix-activity-rows',
                orientation: Clutter.Orientation.VERTICAL});
            this._notificationRow = new St.BoxLayout({style_class: 'jeronix-activity-row'});
            this._activitiesCard = this._card(_('Activities'), [this._rowsBox, this._notificationRow],
                'jeronix-widget-activities');
            this._activitiesBox.add_child(this._activitiesCard);
        }
        items.forEach((item, index) => {
            const view = this._live._view(item.kind, item.data);
            // The panel has room for every control (the expanded set).
            const buttons = view.expandedButtons ?? view.buttons ?? [];
            const shape = viewShape(item.id, item.kind, view, buttons);
            let row = this._rows.get(item.id);
            if (row && row.shape === shape && typeof view.detail === 'string') {
                row.title.text = view.title ?? '';
                row.detail.text = view.detail ?? '';
                row.progress?.setValue(view.progress ?? 0);
                discardView(view);
            } else {
                row?.actor.destroy();
                row = this._activityRow(item.id, view, shape, buttons);
                this._rows.set(item.id, row);
                this._rowsBox.add_child(row.actor);
            }
            this._rowsBox.set_child_at_index(row.actor, index);
            // The one the taskbar shows is marked; a click on another shows it there.
            if (this._live.shownId === item.id)
                row.actor.add_style_class_name('jeronix-activity-shown');
            else
                row.actor.remove_style_class_name('jeronix-activity-shown');
        });
        // Waiting notifications, one click from the notification center.
        this._notificationRow.destroy_all_children();
        this._notificationRow.visible = waiting > 0;
        if (waiting > 0) {
            this._notificationRow.add_child(icon('preferences-system-notifications-symbolic', 'jeronix-activity-icon'));
            this._notificationRow.add_child(new St.Label({text: notificationCount(waiting), x_expand: true,
                style_class: 'jeronix-widget-strong', y_align: Clutter.ActorAlign.CENTER}));
            const open = new St.Button({style_class: 'jeronix-widget-pill', label: _('Open'), can_focus: true});
            open.connect('clicked', () => {
                this.menu.close();
                this._live.notifications.openCenter();
            });
            this._notificationRow.add_child(open);
        }
    }

    /**
     * One activity: icon, two lines and its progress; its controls at the
     * end, or, with more than two, on a line of their own so the title keeps
     * its room. A click on the row shows it in the taskbar.
     */
    _activityRow(id, view, shape, buttons) {
        const actor = new St.Button({style_class: 'jeronix-activity-row', can_focus: true, x_expand: true,
            accessible_name: view.title ?? ''});
        actor.connect('clicked', () => this._live.show(id));
        const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true});
        actor.set_child(box);
        const top = new St.BoxLayout({style_class: 'jeronix-activity-line', x_expand: true});
        box.add_child(top);
        view.icon.add_style_class_name('jeronix-activity-icon');
        top.add_child(view.icon);
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        const title = label(view.title, 'jeronix-widget-strong');
        text.add_child(title);
        const detail = typeof view.detail === 'string' ? label(view.detail, 'jeronix-widget-muted') : null;
        text.add_child(detail ?? view.detail);
        const progress = view.progress !== undefined ? levelBar(view.progress, 'jeronix-activity-progress') : null;
        if (progress)
            text.add_child(progress);
        top.add_child(text);
        for (const button of viewButtons(view).filter(b => !buttons.includes(b)))
            button.destroy();
        if (buttons.length > 2) {
            const controls = new St.BoxLayout({style_class: 'jeronix-activity-controls',
                x_align: Clutter.ActorAlign.CENTER});
            for (const button of buttons)
                controls.add_child(button);
            box.add_child(controls);
        } else {
            for (const button of buttons)
                top.add_child(button);
        }
        return {actor, shape, title, detail, progress, buttons};
    }

    /** The Now Playing card's progress follows the song without a rebuild. */
    _syncMediaProgress() {
        const m = this._live.media?.current;
        if (this._mediaProgress && m?.progress !== undefined)
            this._mediaProgress.setValue(m.progress);
    }

    _timerCard() {
        const timers = this._live.timers;
        if (!timers)
            return null;
        const grid = new St.BoxLayout({style_class: 'jeronix-widget-timers'});
        const add = (text, accessible, start) => {
            const b = new St.Button({style_class: 'jeronix-widget-pill', label: text, can_focus: true,
                accessible_name: accessible, x_expand: true});
            b.connect('clicked', () => start());
            grid.add_child(b);
            this._timerButtons.push(b);
        };
        for (const minutes of TIMER_MINUTES)
            add(`${minutes} min`, `${_('Timer')} ${minutes} min`, () => timers.start(minutes));
        add(_('Focus'), `${_('Focus')} ${FOCUS_MINUTES} min`, () => timers.start(FOCUS_MINUTES, true));
        const hint = label(`${_('Focus')}: ${FOCUS_MINUTES} min, ${_('with Do Not Disturb')}`, 'jeronix-widget-muted');
        return this._card(_('Timer'), [grid, hint]);
    }

    debugState() {
        const rect = a => {
            const [x, y] = a.get_transformed_position();
            const [w, h] = a.get_transformed_size();
            return [x, y, w, h].map(Math.round);
        };
        return {
            activities: [...this._rows.keys()],
            activityButtons: Object.fromEntries([...this._rows].map(([id, row]) => [id,
                row.buttons.filter(b => b.get_parent()).map(b => ({
                    name: b.accessible_name, rect: rect(b),
                }))])),
            notificationsWaiting: Boolean(this._notificationRow?.visible),
            timerButtons: this._timerButtons.map(b => ({name: b.accessible_name, rect: rect(b)})),
        };
    }

    _card(title, children, styleClass = '') {
        const card = new St.BoxLayout({style_class: `jeronix-widget ${styleClass}`,
            orientation: Clutter.Orientation.VERTICAL, x_expand: true});
        if (title)
            card.add_child(label(title, 'jeronix-widget-title'));
        for (const child of children)
            card.add_child(child);
        return card;
    }

    _clockCard() {
        const now = new Date();
        const time = label(this._clock.clock.trim(), 'jeronix-widget-time');
        const date = label(formatDateWithCFormatString(now, Shell.util_translate_time_string('%A, %B %-d')),
            'jeronix-widget-date');
        const grid = new St.Widget({style_class: 'jeronix-widget-calendar', layout_manager: new Clutter.GridLayout(),
            x_expand: true});
        const layout = grid.layout_manager;
        layout.column_homogeneous = true;
        const firstWeekday = Shell.util_get_week_start();
        // Day initials in the session's language, starting with its first weekday.
        for (let i = 0; i < 7; i++) {
            const day = new Date(2024, 0, 7 + (firstWeekday + i) % 7); // 7 Jan 2024 was a Sunday
            layout.attach(label(day.toLocaleDateString(undefined, {weekday: 'narrow'}), 'jeronix-calendar-head'),
                i, 0, 1, 1);
        }
        monthGrid(now, firstWeekday).forEach((week, row) => week.forEach((cell, col) => {
            const classes = ['jeronix-calendar-day'];
            if (!cell.inMonth)
                classes.push('jeronix-calendar-other');
            if (cell.today)
                classes.push('jeronix-calendar-today');
            const day = label(String(cell.day), classes.join(' '));
            day.x_align = Clutter.ActorAlign.CENTER;
            layout.attach(day, col, row + 1, 1, 1);
        }));
        return this._card(null, [time, date, grid], 'jeronix-widget-clock');
    }

    _mediaCard() {
        const m = this._live.media?.current;
        if (!m)
            return null;
        const row = new St.BoxLayout({style_class: 'jeronix-widget-row'});
        row.add_child(icon(this._live._artIcon(m.art), 'jeronix-widget-art'));
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
            y_align: Clutter.ActorAlign.CENTER});
        text.add_child(label(m.title, 'jeronix-widget-strong'));
        if (m.artist)
            text.add_child(label(m.artist, 'jeronix-widget-muted'));
        if (m.progress !== undefined) {
            this._mediaProgress = levelBar(m.progress, 'jeronix-activity-progress');
            text.add_child(this._mediaProgress);
        }
        row.add_child(text);
        this._mediaShown = true;
        const controls = new St.BoxLayout({style_class: 'jeronix-widget-controls', x_align: Clutter.ActorAlign.CENTER});
        const button = (name, accessibleName, callback, sensitive = true) => {
            const b = new St.Button({style_class: 'jeronix-widget-button', can_focus: true, reactive: sensitive,
                accessible_name: accessibleName, child: icon(name, 'jeronix-widget-button-icon')});
            b.connect('clicked', () => callback());
            if (!sensitive)
                b.opacity = 110;
            return b;
        };
        controls.add_child(button('media-skip-backward-symbolic', _('Previous'), m.previous, m.canPrevious));
        controls.add_child(button(m.status === 'Playing' ? 'media-playback-pause-symbolic'
            : 'media-playback-start-symbolic', m.status === 'Playing' ? _('Pause') : _('Play'), m.playPause));
        controls.add_child(button('media-skip-forward-symbolic', _('Next'), m.next, m.canNext));
        return this._card(_('Now Playing'), [row, controls]);
    }

    _weatherCard() {
        const w = this._live.weather;
        if (!w?.available)
            return null; // GNOME Weather is not installed
        const children = [];
        if (!w.hasLocation) {
            children.push(label(_('Choose a location in Weather.'), 'jeronix-widget-muted'));
        } else if (w.info?.is_valid?.()) {
            const row = new St.BoxLayout({style_class: 'jeronix-widget-row'});
            row.add_child(icon(w.info.get_symbolic_icon_name(), 'jeronix-widget-weather-icon'));
            const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL,
                y_align: Clutter.ActorAlign.CENTER});
            text.add_child(label(w.info.get_temp_summary(), 'jeronix-widget-temp'));
            text.add_child(label(w.info.get_sky?.() || w.info.get_conditions?.() || '', 'jeronix-widget-muted'));
            row.add_child(text);
            children.push(row);
            children.push(label(w.info.get_location_name?.() ?? '', 'jeronix-widget-muted'));
        } else {
            children.push(label(w.loading ? _('Loading…') : _('Weather is not available right now.'),
                'jeronix-widget-muted'));
        }
        const card = this._card(_('Weather'), children);
        card.reactive = true;
        card.track_hover = true;
        card.connect('button-release-event', () => {
            this.menu.close();
            w.activateApp();
            return Clutter.EVENT_STOP;
        });
        return card;
    }

    _systemCard() {
        const rows = {};
        const children = [];
        for (const [id, title] of [['cpu', _('Processor')], ['memory', _('Memory')], ['disk', _('Disk')]]) {
            const head = new St.BoxLayout({style_class: 'jeronix-widget-meter-head'});
            head.add_child(label(title, 'jeronix-widget-meter-label'));
            head.add_child(new St.Widget({x_expand: true}));
            const value = label('…', 'jeronix-widget-muted');
            head.add_child(value);
            const bar = levelBar(0, 'jeronix-widget-meter');
            bar.x_expand = true;
            rows[id] = {value, bar};
            children.push(head, bar);
        }
        this._system = rows;
        return this._card(_('System'), children);
    }

    _batteryCard() {
        const power = this._live.power;
        if (!power?.present)
            return null;
        const row = new St.BoxLayout({style_class: 'jeronix-widget-row'});
        row.add_child(icon(power.iconName, 'jeronix-widget-weather-icon'));
        const text = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, y_align: Clutter.ActorAlign.CENTER});
        text.add_child(label(`${power.percentage}%`, 'jeronix-widget-temp'));
        text.add_child(label(power.charging ? _('Charging') : _('On battery'), 'jeronix-widget-muted'));
        row.add_child(text);
        return this._card(_('Battery'), [row]);
    }

    _refreshSystem() {
        const rows = this._system;
        if (!rows)
            return;
        const times = cpuTimes(readText('/proc/stat'));
        const usage = cpuUsage(this._cpu, times);
        this._cpu = times;
        if (usage !== null) {
            rows.cpu.value.text = `${Math.round(usage * 100)}%`;
            rows.cpu.bar.setValue(usage);
        }
        const mem = memory(readText('/proc/meminfo'));
        if (mem) {
            rows.memory.value.text = `${bytes(mem.used)} / ${bytes(mem.total)}`;
            rows.memory.bar.setValue(mem.used / mem.total);
        }
        try {
            const info = Gio.File.new_for_path('/').query_filesystem_info('filesystem::size,filesystem::free', null);
            const size = info.get_attribute_uint64('filesystem::size');
            const free = info.get_attribute_uint64('filesystem::free');
            if (size > 0) {
                rows.disk.value.text = `${bytes(size - free)} / ${bytes(size)}`;
                rows.disk.bar.setValue((size - free) / size);
            }
        } catch (e) {
            rows.disk.value.text = '—';
        }
    }

    destroy() {
        if (this._timer)
            GLib.source_remove(this._timer);
        this._timer = 0;
        this._settings.disconnectObject(this);
        this._clock.run_dispose();
        this.menu.close();
        this._manager.removeMenu(this.menu);
        this.menu.destroy();
        this._anchor.destroy();
    }
}
