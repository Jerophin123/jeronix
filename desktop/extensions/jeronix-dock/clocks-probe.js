// SPDX-License-Identifier: GPL-3.0-or-later
//
// Reads GNOME Clocks' stopwatch and timers over accessibility, for the live
// updates (live.js, ClocksSource). Clocks publishes nothing about them
// itself. Run as its own process (gjs -m clocks-probe.js), so the shell is
// never held up by a slow read: it answers each line on stdin with one line
// of JSON on stdout.
//
//   read                        -> the state (see below)
//   press stopwatch <button>    -> presses the stopwatch's button (0: Start,
//                                  Pause or Resume; 1: Lap or Clear), then reads
//   press timer <row> <button>  -> the same for a timer row's button
//
// The state: {ok, running, stopwatchRunning, timersRunning, stopwatch:
// {text} | null, timers: [{name, text, buttons}] | null}. Clocks only shows
// the content of the page in front, so stopwatch and timers are null when
// theirs is not. Everything is found by role and place, not by (translated)
// text: the tabs are World, Alarms, Stopwatch, Timer, and a tab with a
// description is flagged (running).

import Atspi from 'gi://Atspi?version=2.0';
import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';

const APP_NAME = 'org.gnome.clocks';
const STOPWATCH_TAB = 2;
const TIMER_TAB = 3;
// A timer's countdown, as Clocks writes it: "00 ∶ 04 ∶ 59".
const COUNTDOWN = /^\d+\s*\S\s*\d+\s*\S\s*\d+$/;

Atspi.init();

function findApp() {
    const desktop = Atspi.get_desktop(0);
    for (let i = 0; i < desktop.get_child_count(); i++) {
        const app = desktop.get_child_at_index(i);
        if (app?.get_name() === APP_NAME) {
            // Names change all the time (a running stopwatch): never cached.
            app.set_cache_mask(Atspi.Cache.NONE);
            app.clear_cache();
            return app;
        }
    }
    return null;
}

function children(a) {
    const list = [];
    const n = a.get_child_count();
    for (let i = 0; i < n; i++) {
        const c = a.get_child_at_index(i);
        if (c)
            list.push(c);
    }
    return list;
}

function* walk(a, depth = 0) {
    if (depth > 60)
        return;
    yield a;
    for (const c of children(a))
        yield* walk(c, depth + 1);
}

/** The tabs, and the page shown for each (a panel named as its tab). */
function layout(app) {
    const tabs = [];
    const panels = new Map();
    for (const a of walk(app)) {
        const role = a.get_role();
        if (role === Atspi.Role.PAGE_TAB)
            tabs.push({accessible: a, name: a.get_name(), flagged: Boolean(a.get_description())});
        else if (role === Atspi.Role.PANEL && a.get_name() && !panels.has(a.get_name()))
            panels.set(a.get_name(), a);
    }
    const page = i => (tabs[i] ? panels.get(tabs[i].name) ?? null : null);
    return {tabs, stopwatchPage: page(STOPWATCH_TAB), timerPage: page(TIMER_TAB)};
}

function isButton(a) {
    return a.get_role() === Atspi.Role.BUTTON;
}

/** The stopwatch: its time (the labels before its first button) and buttons. */
function stopwatchOf(page) {
    if (!page || page.get_child_count() === 0)
        return null;
    let text = '';
    const buttons = [];
    for (const a of walk(page)) {
        if (isButton(a))
            buttons.push(a);
        else if (!buttons.length && a.get_role() === Atspi.Role.LABEL)
            text += a.get_name();
    }
    return text ? {text, buttons} : null;
}

/** The timers: each countdown, its name and the buttons after it. */
function timersOf(page) {
    if (!page || page.get_child_count() === 0)
        return null;
    const rows = [];
    for (const a of walk(page)) {
        const role = a.get_role();
        const name = a.get_name() ?? '';
        if (role === Atspi.Role.LABEL && COUNTDOWN.test(name.trim()))
            rows.push({text: name.trim(), name: '', buttons: []});
        else if (!rows.length)
            continue;
        else if (isButton(a))
            rows.at(-1).buttons.push(a);
        else if (role === Atspi.Role.LABEL && name && !rows.at(-1).name && !rows.at(-1).buttons.length)
            rows.at(-1).name = name;
    }
    return rows;
}

function read() {
    const app = findApp();
    if (!app)
        return {ok: true, running: false};
    const {tabs, stopwatchPage, timerPage} = layout(app);
    const stopwatch = stopwatchOf(stopwatchPage);
    const timers = timersOf(timerPage);
    return {
        ok: true, running: true,
        stopwatchRunning: Boolean(tabs[STOPWATCH_TAB]?.flagged),
        timersRunning: Boolean(tabs[TIMER_TAB]?.flagged),
        stopwatch: stopwatch ? {text: stopwatch.text} : null,
        timers: timers ? timers.map(t => ({name: t.name, text: t.text, buttons: t.buttons.length})) : null,
        _stopwatchButtons: stopwatch?.buttons ?? [],
        _timerButtons: timers?.map(t => t.buttons) ?? [],
        _tabs: tabs,
    };
}

function press(what, args) {
    let state = read();
    if (!state.running)
        return state;
    const find = s => (what === 'stopwatch' ? s._stopwatchButtons[args[0]]
        : s._timerButtons[args[0]]?.[args[1]]);
    if (!find(state)) {
        // Its page is not in front: bring it there (a tab click), then look again.
        state._tabs[what === 'stopwatch' ? STOPWATCH_TAB : TIMER_TAB]?.accessible.do_action(0);
        GLib.usleep(250000);
        state = read();
    }
    const button = find(state);
    let pressed = false;
    if (button) {
        pressed = button.do_action(0);
        GLib.usleep(150000); // let Clocks update before reading it again
    }
    return {...read(), pressed};
}

function answer(line) {
    const [command, what, ...rest] = line.trim().split(/\s+/);
    try {
        const state = command === 'press' ? press(what, rest.map(Number)) : read();
        return JSON.stringify(state, (key, value) => (key.startsWith('_') ? undefined : value));
    } catch (e) {
        return JSON.stringify({ok: false, error: String(e)});
    }
}

const input = new Gio.DataInputStream({base_stream: new GioUnix.InputStream({fd: 0, close_fd: false})});
const output = new Gio.DataOutputStream({base_stream: new GioUnix.OutputStream({fd: 1, close_fd: false})});
for (;;) {
    const [line] = input.read_line_utf8(null);
    if (line === null)
        break; // the shell is gone
    if (line.trim())
        output.put_string(`${answer(line)}\n`, null);
}
