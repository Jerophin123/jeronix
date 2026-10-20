// SPDX-License-Identifier: GPL-3.0-or-later
//
// The logic of the taskbar's live updates, without Shell imports
// (unit-tested with plain gjs: tests/unit/js/test_live_model.js).
//
// Activities are what the live updates show. Some go on until they end
// (music, a timer, a recording, the microphone in use): ongoing activities.
// Others are glimpses of a change (volume, a notification, Caps Lock) that
// end by themselves. The area shows:
//
//  1. the newest, most important glimpse, if any: glimpses are brief, so
//     they always get their moment;
//  2. else the ongoing activity the person chose (scrolling over the area
//     cycles through them);
//  3. else the most important ongoing activity.
//
// Everything else ongoing stays reachable: a "+N" count on the area, the
// scroll wheel, and the Activities card in the widgets panel.

// Importance, higher first: which glimpse, or which ongoing activity, wins.
export const PRIORITY = {
    // ongoing
    recording: 100,
    privacy: 95, // microphone or camera in use
    'battery-low': 75,
    timer: 60,
    stopwatch: 58, // GNOME Clocks' stopwatch
    media: 50,
    download: 40,
    'stay-awake': 20,
    dnd: 15, // Do Not Disturb on

    // glimpses
    level: 90,
    notification: 80,
    'timer-done': 78,
    power: 70,
    network: 65,
    downloaded: 62,
    keyboard: 60,
    mic: 88, // microphone muted or unmuted
    'input-source': 58, // keyboard layout switched
    workspace: 55,
};

// How long glimpses stay, in milliseconds.
export const GLIMPSE_MS = {
    level: 1600,
    notification: 4500,
    'timer-done': 8000,
    power: 3500,
    network: 3500,
    downloaded: 6000,
    keyboard: 1500,
    mic: 1600,
    'input-source': 1800,
    workspace: 1400,
};

// A paused player stays this long before the area lets it go.
export const PAUSED_MS = 30000;

// What the live updates can show, as chosen in Settings (live-activities):
// setting id -> the activity kinds it covers.
export const ACTIVITY_GROUPS = {
    media: ['media'],
    timers: ['timer', 'timer-done', 'stopwatch'],
    recording: ['recording'],
    privacy: ['privacy'],
    downloads: ['download', 'downloaded'],
    levels: ['level', 'mic'],
    notifications: ['notification'],
    battery: ['power', 'battery-low'],
    network: ['network'],
    keyboard: ['keyboard', 'input-source'],
    'stay-awake': ['stay-awake'],
    'do-not-disturb': ['dnd'],
    workspaces: ['workspace'],
};

/** Activity kinds allowed by the live-activities setting. */
export function allowedKinds(setting) {
    return new Set(setting.flatMap(id => ACTIVITY_GROUPS[id] ?? []));
}

// The widgets the panel can show, in their default order.
export const WIDGETS = ['clock', 'timer', 'media', 'weather', 'system', 'battery'];

// Quick timers offered in the Timer widget, in minutes; the last one is a
// focus session (Do Not Disturb for its length).
export const TIMER_MINUTES = [1, 5, 10];
export const FOCUS_MINUTES = 25;

export class Activities {
    constructor() {
        this._items = new Map();
        this._serial = 0;
        this._pinned = null;
    }

    /**
     * Shows (or updates) activity id. A glimpse (durationMs) ends by itself;
     * otherwise it is ongoing until remove(id).
     */
    set(id, kind, data = {}, now = 0, durationMs = null) {
        const old = this._items.get(id);
        this._items.set(id, {
            id, kind, data,
            priority: PRIORITY[kind] ?? 0,
            // Updating an activity in place keeps its place among equals.
            serial: old && old.kind === kind ? old.serial : ++this._serial,
            expires: durationMs === null ? null : now + durationMs,
        });
    }

    remove(id) {
        if (this._pinned === id)
            this._pinned = null;
        return this._items.delete(id);
    }

    has(id) {
        return this._items.has(id);
    }

    _prune(now) {
        for (const [id, item] of this._items) {
            if (item.expires !== null && item.expires <= now)
                this.remove(id);
        }
    }

    static _better(a, b) {
        return !b || a.priority > b.priority || (a.priority === b.priority && a.serial > b.serial);
    }

    /** Ongoing activities, most important first. */
    ongoing(now) {
        this._prune(now);
        return [...this._items.values()].filter(i => i.expires === null)
            .sort((a, b) => b.priority - a.priority || b.serial - a.serial);
    }

    /** The activity to show now (see the top of this file), or null. */
    current(now) {
        this._prune(now);
        let glimpse = null;
        for (const item of this._items.values()) {
            if (item.expires !== null && Activities._better(item, glimpse))
                glimpse = item;
        }
        if (glimpse)
            return glimpse;
        if (this._pinned)
            return this._items.get(this._pinned);
        return this.ongoing(now)[0] ?? null;
    }

    /**
     * Shows the next (step 1) or previous (step -1) ongoing activity, and
     * keeps showing it until it ends or another is chosen. Returns its id.
     */
    cycle(step, now) {
        const list = this.ongoing(now);
        if (list.length < 2)
            return list[0]?.id ?? null;
        const shown = this._pinned ?? list[0].id;
        const index = list.findIndex(i => i.id === shown);
        const next = list[(index + step + list.length) % list.length];
        this._pinned = next.id;
        return next.id;
    }

    /** Shows ongoing activity id until it ends or another is chosen. */
    show(id) {
        const item = this._items.get(id);
        if (!item || item.expires !== null)
            return false;
        this._pinned = id;
        return true;
    }

    get pinned() {
        return this._pinned;
    }

    /** Milliseconds until the next glimpse ends, or null if none will. */
    nextChange(now) {
        this._prune(now);
        let next = null;
        for (const item of this._items.values()) {
            if (item.expires !== null)
                next = next === null ? item.expires - now : Math.min(next, item.expires - now);
        }
        return next;
    }
}

/** A countdown that can be paused, in milliseconds of the caller's clock. */
export class Countdown {
    constructor(durationMs, now) {
        this.duration = durationMs;
        this._end = now + durationMs;
        this._pausedLeft = null;
    }

    get paused() {
        return this._pausedLeft !== null;
    }

    remaining(now) {
        return Math.max(0, this.paused ? this._pausedLeft : this._end - now);
    }

    done(now) {
        return !this.paused && this.remaining(now) === 0;
    }

    pause(now) {
        if (!this.paused)
            this._pausedLeft = this.remaining(now);
    }

    resume(now) {
        if (this.paused) {
            this._end = now + this._pausedLeft;
            this._pausedLeft = null;
        }
    }

    /** Adds ms to the time left (the "+1 min" button). */
    add(ms, now) {
        this.duration += ms;
        if (this.paused)
            this._pausedLeft += ms;
        else
            this._end = Math.max(this._end, now) + ms;
    }

    /** 0..1 of the time gone by, for a progress bar. */
    progress(now) {
        return this.duration > 0 ? 1 - this.remaining(now) / this.duration : 1;
    }
}

/** "4:59" left, rounding up, so a countdown never shows 0:00 before it ends. */
export function remainingText(ms) {
    return elapsed(Math.ceil(Math.max(0, ms) / 1000));
}

// -- GNOME Clocks ------------------------------------------------------------------
//
// Clocks publishes nothing about its stopwatch and timers, so the live
// updates read them from its window over accessibility (clocks-probe.js),
// whenever it is in front, and count on by themselves in between: what a
// read gives is only trusted as far as it can be. Clocks draws its
// stopwatch only while its window is shown, so a read of a hidden window
// is behind; its timers count on a timeout and are always right, but only
// the page shown is readable. Its tabs flag, on any page, whether the
// stopwatch and any timer are running.

/** Seconds in a Clocks time: "00∶01∶34.9" (stopwatch) or "00 ∶ 04 ∶ 59" (timer). */
export function clocksSeconds(text) {
    const m = /(?:(\d+)\D+)?(\d+)\D+(\d+)(?:\.(\d))?\s*$/.exec(text ?? '');
    if (!m)
        return null;
    const [, h, min, s, tenths] = m;
    return Number(h ?? 0) * 3600 + Number(min) * 60 + Number(s) + Number(tenths ?? 0) / 10;
}

/** A Clocks timer row's state, from how many buttons it shows. */
export function clocksTimerState(buttons) {
    // Running: Pause. Paused: Start, Reset, Delete. Stopped: Start, Delete.
    return {1: 'running', 3: 'paused', 2: 'stopped'}[buttons] ?? null;
}

export class ClocksTracker {
    constructor() {
        this.clear();
    }

    clear() {
        this.stopwatch = null; // {base (s), at (ms), running}
        this.timers = new Map(); // row index -> {name, base (s), at (ms), running, total (s)}
    }

    /**
     * Takes a read of Clocks at time now (ms): {stopwatchRunning,
     * timersRunning, stopwatch: {text} or null, timers: [{name, text,
     * buttons}] or null}; null parts were not on the page shown.
     * durations: the timers' lengths in seconds, by row (Clocks' settings).
     */
    update(read, now, durations = []) {
        this._updateStopwatch(read, now);
        this._updateTimers(read, now, durations);
    }

    _stopwatchAt(now) {
        const s = this.stopwatch;
        return s ? s.base + (s.running ? (now - s.at) / 1000 : 0) : 0;
    }

    _updateStopwatch(read, now) {
        const running = Boolean(read.stopwatchRunning);
        const shown = read.stopwatch ? clocksSeconds(read.stopwatch.text) : null;
        const before = this.stopwatch;
        if (shown === null) {
            // Not on the page shown: only whether it runs is known.
            if (running && !before?.running)
                this.stopwatch = {base: before?.base ?? 0, at: now, running: true};
            else if (!running && before?.running)
                this.stopwatch = {base: this._stopwatchAt(now), at: now, running: false};
            return;
        }
        if (!running) {
            this.stopwatch = shown > 0 ? {base: shown, at: now, running: false} : null; // paused, or reset
        } else if (before?.running && shown < this._stopwatchAt(now) - 0.5) {
            // Behind what is known: a hidden window's stale time. Keep counting.
        } else {
            this.stopwatch = {base: shown, at: now, running: true};
        }
    }

    _timerAt(t, now) {
        return Math.max(0, t.base - (t.running ? (now - t.at) / 1000 : 0));
    }

    _updateTimers(read, now, durations) {
        if (read.timers) {
            const next = new Map();
            read.timers.forEach((row, index) => {
                const state = clocksTimerState(row.buttons);
                const left = clocksSeconds(row.text);
                if (left === null || (state !== 'running' && state !== 'paused'))
                    return;
                const running = state === 'running';
                const before = this.timers.get(index);
                // A running timer read again within a second of where it is
                // counted keeps counting smoothly (Clocks rounds up).
                const smooth = before?.running && running && Math.abs(this._timerAt(before, now) - left) < 1.5;
                next.set(index, smooth ? {...before, name: row.name ?? ''} : {
                    name: row.name ?? '', base: left, at: now, running,
                    total: Math.max(durations[index] ?? 0, left),
                });
            });
            this.timers = next;
        } else if (!read.timersRunning) {
            // None runs any more: each was paused there, or rang.
            for (const [index, t] of this.timers) {
                if (!t.running)
                    continue;
                const left = this._timerAt(t, now);
                if (left <= 1.5)
                    this.timers.delete(index);
                else
                    this.timers.set(index, {...t, base: left, at: now, running: false});
            }
        }
    }

    /** What to show at now (ms): {stopwatch: {seconds, running} | null, timers: [...]}. */
    state(now) {
        for (const [index, t] of this.timers) {
            if (t.running && this._timerAt(t, now) <= 0)
                this.timers.delete(index); // rung: Clocks tells about it itself
        }
        return {
            stopwatch: this.stopwatch ? {seconds: this._stopwatchAt(now), running: this.stopwatch.running} : null,
            timers: [...this.timers].map(([index, t]) => ({
                index, name: t.name, seconds: this._timerAt(t, now), running: t.running,
                progress: t.total > 0 ? 1 - this._timerAt(t, now) / t.total : undefined,
            })),
        };
    }

    get active() {
        return Boolean(this.stopwatch?.running) || [...this.timers.values()].some(t => t.running);
    }
}

// Browsers write a download under a temporary name, then rename it.
const PARTIAL_SUFFIXES = ['.crdownload', '.part', '.partial', '.download', '.opdownload'];

/** The final name of a file being downloaded, or null if it is not one. */
export function partialDownload(name) {
    const suffix = PARTIAL_SUFFIXES.find(s => name.toLowerCase().endsWith(s) && name.length > s.length);
    if (!suffix)
        return null;
    const final = name.slice(0, -suffix.length);
    // Chromium's "Unconfirmed 123456.crdownload" has no final name yet.
    return /^Unconfirmed \d+$/.test(final) ? '' : final;
}

// Volume controls themselves record from every microphone to show levels.
const MIC_IGNORED = ['org.gnome.VolumeControl', 'org.PulseAudio.pavucontrol', 'org.gnome.Settings',
    'io.jeronix.Settings'];

/** The apps recording from a microphone: [{id, name}] of mixer source outputs. */
export function microphoneUsers(outputs) {
    const seen = new Set();
    const users = [];
    for (const o of outputs) {
        if (MIC_IGNORED.includes(o.id))
            continue;
        const name = o.name || o.id || 'An app';
        if (!seen.has(name)) {
            seen.add(name);
            users.push(name);
        }
    }
    return users;
}

/**
 * What a network change means for a person, or null when it is not worth a
 * glimpse. before/after: {connected, name, wifi} (connected: has a primary
 * connection; name: its name; wifi: whether it is wireless).
 */
export function networkChange(before, after) {
    if (!before)
        return null; // the first reading, not a change
    if (after.connected && (!before.connected || before.name !== after.name))
        return {text: 'Connected', detail: after.name, icon: after.wifi ? 'network-wireless-symbolic'
            : 'network-wired-symbolic'};
    if (!after.connected && before.connected)
        return {text: 'Offline', detail: 'No network connection', icon: 'network-offline-symbolic'};
    return null;
}

/** "1 notification", "3 notifications": the idle glance when some are waiting. */
export function notificationCount(n) {
    return n === 1 ? '1 notification' : `${n} notifications`;
}

/** "0:07", "12:34", "1:02:03": elapsed time, as on a phone's timer. */
export function elapsed(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor(s % 3600 / 60);
    const pad = n => String(n).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

/** [busy, total] jiffies from the first line of /proc/stat, or null. */
export function cpuTimes(procStat) {
    const line = procStat.split('\n').find(l => l.startsWith('cpu '));
    if (!line)
        return null;
    const v = line.trim().split(/\s+/).slice(1).map(Number);
    if (v.length < 4 || v.some(n => !Number.isFinite(n)))
        return null;
    // user nice system idle iowait irq softirq steal (guest is inside user)
    const idle = v[3] + (v[4] ?? 0);
    const total = v.slice(0, 8).reduce((a, b) => a + b, 0);
    return [total - idle, total];
}

/** CPU use between two cpuTimes() samples, 0..1, or null. */
export function cpuUsage(before, after) {
    if (!before || !after)
        return null;
    const total = after[1] - before[1];
    if (total <= 0)
        return null;
    return Math.min(1, Math.max(0, (after[0] - before[0]) / total));
}

/** {used, total} bytes from /proc/meminfo, or null. */
export function memory(procMeminfo) {
    const kb = {};
    for (const line of procMeminfo.split('\n')) {
        const m = line.match(/^(\w+):\s+(\d+)/);
        if (m)
            kb[m[1]] = Number(m[2]);
    }
    if (!kb.MemTotal || kb.MemAvailable === undefined)
        return null;
    return {used: (kb.MemTotal - kb.MemAvailable) * 1024, total: kb.MemTotal * 1024};
}

/** "3.4 GB", "512 MB": a size for a small widget. */
export function bytes(n) {
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = Math.max(0, n);
    let i = 0;
    while (v >= 1000 && i < units.length - 1) {
        v /= 1000;
        i++;
    }
    return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

/**
 * The month around date as weeks of 7 days (Monday first by default):
 * [[{day, inMonth, today}]], for the calendar widget.
 */
export function monthGrid(date, firstWeekday = 1, today = date) {
    const first = new Date(date.getFullYear(), date.getMonth(), 1);
    const offset = (first.getDay() - firstWeekday + 7) % 7;
    const start = new Date(first.getFullYear(), first.getMonth(), 1 - offset);
    const weeks = [];
    for (let w = 0; w < 6; w++) {
        const week = [];
        for (let d = 0; d < 7; d++) {
            const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + w * 7 + d);
            week.push({
                day: day.getDate(),
                inMonth: day.getMonth() === date.getMonth(),
                today: day.toDateString() === today.toDateString(),
            });
        }
        // A sixth week only when the month needs it.
        if (w === 5 && !week.some(c => c.inMonth))
            break;
        weeks.push(week);
    }
    return weeks;
}

/** The widgets to show: known ids from the setting, in its order, once each. */
export function widgetList(setting) {
    const seen = new Set();
    return setting.filter(id => WIDGETS.includes(id) && !seen.has(id) && seen.add(id));
}

// -- dynamic colors ----------------------------------------------------------------
//
// The live updates take the color of what is going on, as the Dynamic
// Island and the Now Bar do: red while recording, orange for a timer, the
// album's own color for music. 'accent' uses the system accent for
// everything, 'neutral' no color at all (live-colors).

export const COLOR_MODES = ['dynamic', 'accent', 'neutral'];

// GNOME's accent colors (org.gnome.desktop.interface accent-color).
export const ACCENTS = {
    blue: [53, 132, 228], teal: [33, 144, 164], green: [58, 148, 74], yellow: [200, 136, 0],
    orange: [237, 91, 0], red: [230, 45, 66], pink: [213, 97, 153], purple: [145, 65, 172], slate: [111, 131, 150],
};

// What each activity looks like with dynamic colors; null: no color.
export const TINTS = {
    recording: [230, 45, 66],
    privacy: [237, 91, 0],
    camera: [58, 148, 74],
    'battery-low': [230, 45, 66],
    timer: [245, 128, 20],
    'timer-done': [245, 128, 20],
    stopwatch: [245, 128, 20],
    focus: [110, 96, 230],
    media: [145, 65, 172],
    download: [53, 132, 228],
    downloaded: [53, 132, 228],
    network: [33, 144, 164],
    offline: [140, 140, 150],
    power: [58, 160, 74],
    'stay-awake': [214, 150, 0],
    dnd: [110, 96, 230],
    notification: 'accent',
    waiting: 'accent',
    weather: [56, 150, 220],
    workspace: [53, 132, 228],
    mic: [237, 91, 0],
    level: null,
    keyboard: null,
    'input-source': null,
    idle: null,
};

/** Which entry of TINTS an activity uses. */
export function tintKey(kind, data = {}) {
    if (kind === 'timer' && data.focus)
        return 'focus';
    if (kind === 'privacy' && data.camera)
        return 'camera';
    if (kind === 'network' && data.offline)
        return 'offline';
    if (kind === 'mic' && !data.muted)
        return 'level';
    if (kind === 'idle')
        return data.glance ?? 'idle';
    return kind;
}

/**
 * The color [r, g, b] of an activity, or null for none. data.color (the
 * album art's color, for music) wins in the dynamic mode.
 */
export function tintFor(kind, data, mode, accent) {
    if (mode === 'neutral')
        return null;
    const key = tintKey(kind, data);
    const tint = TINTS[key] ?? null;
    if (mode === 'accent')
        return tint === null ? null : accent;
    if (kind === 'media' && data?.color)
        return data.color;
    return tint === 'accent' ? accent : tint;
}

/** The inline style that tints the live updates (strength: 0..1). */
export function tintStyle(rgb, strength = 1) {
    if (!rgb)
        return '';
    const [r, g, b] = rgb.map(v => Math.round(v));
    const a = n => (n * strength).toFixed(2);
    return `background-color: rgba(${r}, ${g}, ${b}, ${a(0.24)}); ` +
        `box-shadow: inset 0 0 0 1px rgba(${r}, ${g}, ${b}, ${a(0.55)});`;
}

/**
 * The most telling color of an image (album art): the average of its
 * colorful pixels, weighted by how colorful they are, brightened a little
 * so it reads as a color. null for a grey image.
 *
 * @param {Uint8Array} pixels - RGB(A) rows
 */
export function dominantColor(pixels, width, height, rowstride, channels) {
    let r = 0, g = 0, b = 0, weight = 0;
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const i = y * rowstride + x * channels;
            const pr = pixels[i], pg = pixels[i + 1], pb = pixels[i + 2];
            if (channels === 4 && pixels[i + 3] < 128)
                continue;
            const max = Math.max(pr, pg, pb), min = Math.min(pr, pg, pb);
            const saturation = max === 0 ? 0 : (max - min) / max;
            // Colorful, not too dark: what a person sees as "the color".
            const w = saturation * saturation * (max / 255);
            r += pr * w;
            g += pg * w;
            b += pb * w;
            weight += w;
        }
    }
    if (weight < width * height * 0.02)
        return null;
    const color = [r / weight, g / weight, b / weight];
    const top = Math.max(...color);
    const lift = top < 170 ? 170 / Math.max(1, top) : 1;
    return color.map(v => Math.min(255, Math.round(v * lift)));
}
