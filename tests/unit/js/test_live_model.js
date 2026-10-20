// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_live_model.js

import System from 'system';

import {ACCENTS, ACTIVITY_GROUPS, Activities, ClocksTracker, Countdown, GLIMPSE_MS, PAUSED_MS, PRIORITY, TINTS, WIDGETS,
    allowedKinds, bytes, cpuTimes, cpuUsage, dominantColor, elapsed, memory, microphoneUsers, monthGrid, networkChange,
    clocksSeconds, clocksTimerState, notificationCount, partialDownload, remainingText, tintFor, tintKey, tintStyle, widgetList} from '../../../desktop/extensions/jeronix-dock/live-model.js';

let failures = 0;
let count = 0;

function assertEq(actual, expected, what) {
    if (JSON.stringify(actual) !== JSON.stringify(expected))
        throw new Error(`${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

function test(name, fn) {
    count++;
    try {
        fn();
        print(`ok - ${name}`);
    } catch (e) {
        failures++;
        print(`FAIL - ${name}: ${e.message}`);
    }
}

test('nothing to show when idle', () => {
    const a = new Activities();
    assertEq(a.current(0), null, 'idle');
    assertEq(a.nextChange(0), null, 'no timer when idle');
});

test('the most important activity wins', () => {
    const a = new Activities();
    a.set('media', 'media', {title: 'Song'}, 0);
    a.set('rec', 'recording', {}, 0);
    a.set('awake', 'stay-awake', {}, 0);
    assertEq(a.current(0).id, 'rec', 'recording above music and Stay Awake');
    a.remove('rec');
    assertEq(a.current(0).id, 'media', 'music once recording stops');
});

test('a glimpse shows over music, then ends by itself', () => {
    const a = new Activities();
    a.set('media', 'media', {}, 0);
    a.set('level', 'level', {value: 0.5}, 1000, GLIMPSE_MS.level);
    assertEq(a.current(1000).id, 'level', 'volume change on top');
    assertEq(a.nextChange(1000), GLIMPSE_MS.level, 'the area knows when to change back');
    assertEq(a.current(1000 + GLIMPSE_MS.level - 1).id, 'level', 'still showing just before the end');
    assertEq(a.current(1000 + GLIMPSE_MS.level).id, 'media', 'back to music after');
    assertEq(a.nextChange(1000 + GLIMPSE_MS.level), null, 'no timer left');
});

test('an updated glimpse restarts its time', () => {
    const a = new Activities();
    a.set('level', 'level', {value: 0.2}, 0, 1000);
    a.set('level', 'level', {value: 0.3}, 800, 1000);
    assertEq(a.current(1500).data.value, 0.3, 'the newest value, still showing');
    assertEq(a.current(1800), null, 'gone 1000 ms after the last change');
});

test('among equals, the newest wins; updates keep their place', () => {
    const a = new Activities();
    a.set('n1', 'notification', {title: 'one'}, 0, 5000);
    a.set('n2', 'notification', {title: 'two'}, 10, 5000);
    assertEq(a.current(20).id, 'n2', 'newest notification');
    a.set('n1', 'notification', {title: 'one (edited)'}, 30, 5000);
    assertEq(a.current(40).id, 'n2', 'editing an older one does not jump ahead');
});

test('priorities and timings are sane', () => {
    assertEq(PRIORITY.recording > PRIORITY.level && PRIORITY.level > PRIORITY.notification &&
        PRIORITY.notification > PRIORITY.media && PRIORITY.media > PRIORITY['stay-awake'], true, 'order');
    assertEq(Object.values(GLIMPSE_MS).every(ms => ms >= 1000 && ms <= 8000), true, 'glimpses are short');
    assertEq(PAUSED_MS >= 10000, true, 'a paused song lingers');
});

test('elapsed time reads like a timer', () => {
    assertEq(elapsed(0), '0:00', 'zero');
    assertEq(elapsed(7.9), '0:07', 'seconds');
    assertEq(elapsed(754), '12:34', 'minutes');
    assertEq(elapsed(3723), '1:02:03', 'hours');
    assertEq(elapsed(-5), '0:00', 'never negative');
});

test('CPU use from /proc/stat', () => {
    const a = cpuTimes('cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 1 2 3 4\n');
    const b = cpuTimes('cpu  200 0 100 850 50 0 0 0 0 0\n');
    assertEq(a, [150, 1000], 'busy and total');
    assertEq(cpuUsage(a, b), 0.75, '150 busy of 200');
    assertEq(cpuUsage(b, b), null, 'no time passed');
    assertEq(cpuTimes('garbage'), null, 'unreadable');
    assertEq(cpuUsage(null, b), null, 'first sample');
});

test('memory from /proc/meminfo', () => {
    const m = memory('MemTotal:       8000000 kB\nMemFree:  100 kB\nMemAvailable:   6000000 kB\n');
    assertEq(m, {used: 2000000 * 1024, total: 8000000 * 1024}, 'used is total minus available');
    assertEq(memory('MemTotal: 10 kB\n'), null, 'needs MemAvailable');
});

test('sizes read naturally', () => {
    assertEq(bytes(0), '0 B', 'zero');
    assertEq(bytes(512e6), '512 MB', 'megabytes');
    assertEq(bytes(3.44e9), '3.4 GB', 'one decimal under ten');
    assertEq(bytes(16e12), '16 TB', 'large');
});

test('the month grid', () => {
    // October 2026 starts on a Thursday.
    const oct = monthGrid(new Date(2026, 9, 18), 1);
    assertEq(oct[0].map(c => c.day), [28, 29, 30, 1, 2, 3, 4], 'Monday-first first week');
    assertEq(oct[0][2].inMonth, false, 'September days are marked');
    assertEq(oct.flat().filter(c => c.today).map(c => c.day), [18], 'today');
    assertEq(oct.flat().filter(c => c.inMonth).length, 31, 'every day of October');
    assertEq(oct.every(w => w.length === 7), true, 'full weeks');
    const sunday = monthGrid(new Date(2026, 9, 18), 0);
    assertEq(sunday[0].map(c => c.day), [27, 28, 29, 30, 1, 2, 3], 'Sunday-first');
    // February 2027 fits in four Monday-first weeks... plus none extra.
    const feb = monthGrid(new Date(2027, 1, 10), 1);
    assertEq(feb.length <= 6 && feb.length >= 4, true, 'no empty sixth week');
    assertEq(feb.flat().filter(c => c.inMonth).length, 28, 'February 2027');
    assertEq(monthGrid(new Date(2026, 9, 18), 1, new Date(2026, 10, 1)).flat().some(c => c.today), true,
        'today shown when it falls in a neighbouring month\'s cells');
});

test('widget list follows the setting, ignoring unknown and repeated ids', () => {
    assertEq(widgetList(['system', 'clock', 'nope', 'clock', 'media']), ['system', 'clock', 'media'], 'filtered');
    assertEq(widgetList(WIDGETS), WIDGETS, 'default');
    assertEq(widgetList([]), [], 'none');
});

test('a glimpse always gets its moment, even over a recording', () => {
    const a = new Activities();
    a.set('rec', 'recording', {}, 0);
    a.set('caps', 'keyboard', {}, 100, 1500);
    assertEq(a.current(200).id, 'caps', 'the brief glimpse shows');
    assertEq(a.current(1700).id, 'rec', 'then the recording again');
});

test('scrolling cycles through ongoing activities and keeps the choice', () => {
    const a = new Activities();
    a.set('rec', 'recording', {}, 0);
    a.set('timer', 'timer', {}, 0);
    a.set('media', 'media', {}, 0);
    assertEq(a.ongoing(0).map(i => i.id), ['rec', 'timer', 'media'], 'most important first');
    assertEq(a.cycle(1, 0), 'timer', 'next');
    assertEq(a.current(0).id, 'timer', 'the chosen one shows');
    a.set('media', 'media', {title: 'next song'}, 10);
    assertEq(a.current(10).id, 'timer', 'updates elsewhere do not take over');
    assertEq(a.cycle(1, 10), 'media', 'next again');
    assertEq(a.cycle(1, 10), 'rec', 'wraps around');
    assertEq(a.cycle(-1, 10), 'media', 'and back');
    a.set('vol', 'level', {}, 20, 1000);
    assertEq(a.current(30).id, 'vol', 'a glimpse still shows over the choice');
    assertEq(a.current(1100).id, 'media', 'and the choice comes back');
    a.remove('media');
    assertEq(a.pinned, null, 'a chosen activity that ends is forgotten');
    assertEq(a.current(1100).id, 'rec', 'the most important one shows again');
    const one = new Activities();
    one.set('m', 'media', {}, 0);
    assertEq(one.cycle(1, 0), 'm', 'nothing to cycle with one');
    assertEq(one.pinned, null, 'and nothing is pinned');
});

test('an activity chosen in the widgets panel shows', () => {
    const a = new Activities();
    a.set('rec', 'recording', {}, 0);
    a.set('media', 'media', {}, 0);
    a.set('vol', 'level', {}, 0, 1000);
    assertEq(a.show('media'), true, 'an ongoing one can be chosen');
    assertEq(a.current(2000).id, 'media', 'and shows');
    assertEq(a.show('vol'), false, 'a glimpse cannot');
    assertEq(a.show('gone'), false, 'nor something unknown');
    assertEq(a.pinned, 'media', 'the choice stays');
    assertEq(a.cycle(1, 2000), 'rec', 'cycling goes on from the choice');
});

test('Clocks times are read as Clocks writes them', () => {
    assertEq(clocksSeconds('00∶01∶34.9'), 94.9, 'the stopwatch, with tenths');
    assertEq(clocksSeconds('01 ∶ 04 ∶ 59'), 3899, 'a timer');
    assertEq(clocksSeconds('04∶59'), 299, 'without hours');
    assertEq(clocksSeconds('Stopwatch'), null, 'not a time');
    assertEq([1, 2, 3, 0].map(clocksTimerState), ['running', 'stopped', 'paused', null], 'a row by its buttons');
});

test('the Clocks stopwatch counts on between reads, never back', () => {
    const c = new ClocksTracker();
    const read = (running, text) => ({stopwatchRunning: running, timersRunning: false,
        stopwatch: text === null ? null : {text}, timers: null});
    c.update(read(true, '00∶00∶10.0'), 0);
    assertEq(c.state(5000).stopwatch, {seconds: 15, running: true}, 'counts on by itself');
    c.update(read(true, '00∶00∶10.0'), 5000); // a hidden window: drawn last at 10 s
    assertEq(c.state(6000).stopwatch.seconds, 16, 'a stale read is not taken');
    c.update(read(true, null), 7000); // another page in front
    assertEq(c.state(7000).stopwatch.seconds, 17, 'counts on with its page away');
    c.update(read(false, '00∶00∶20.0'), 10000);
    assertEq(c.state(30000).stopwatch, {seconds: 20, running: false}, 'paused where Clocks says');
    assertEq(c.active, false, 'nothing runs');
    c.update(read(false, '00∶00∶00.0'), 31000);
    assertEq(c.state(31000).stopwatch, null, 'reset: gone');
    c.update(read(true, null), 32000);
    assertEq(c.state(33000).stopwatch, {seconds: 1, running: true}, 'started from another page');
});

test('Clocks timers: running, paused and rung', () => {
    const c = new ClocksTracker();
    const rows = [{name: 'Tea', text: '00 ∶ 04 ∶ 00', buttons: 1}, {name: '', text: '00 ∶ 01 ∶ 00', buttons: 3},
        {name: '', text: '00 ∶ 05 ∶ 00', buttons: 2}];
    c.update({stopwatchRunning: false, timersRunning: true, stopwatch: null, timers: rows}, 0, [300, 60, 300]);
    let s = c.state(60000).timers;
    assertEq(s.map(t => [t.index, t.name, t.seconds, t.running]), [[0, 'Tea', 180, true], [1, '', 60, false]],
        'a stopped row is not shown; the running one counts down');
    assertEq(s[0].progress, 0.4, 'progress from its length in Clocks');
    c.update({stopwatchRunning: false, timersRunning: true, stopwatch: null, timers: null}, 120000);
    assertEq(c.state(120000).timers[0].seconds, 120, 'counts on with its page away');
    assertEq(c.state(240000).timers.map(t => t.index), [1], 'rung: gone');
    const p = new ClocksTracker();
    p.update({timersRunning: true, timers: [rows[0]]}, 0);
    p.update({timersRunning: false, timers: null}, 60000);
    assertEq(p.state(90000).timers.map(t => [t.seconds, t.running]), [[180, false]], 'none runs any more: paused');
});

test('a countdown counts down, pauses and ends', () => {
    const c = new Countdown(60000, 1000);
    assertEq(c.remaining(31000), 30000, 'half way');
    assertEq(remainingText(c.remaining(31000)), '0:30', 'as text');
    assertEq(remainingText(29001), '0:30', 'rounds up: never 0:00 before the end');
    c.pause(31000);
    assertEq(c.remaining(50000), 30000, 'paused: time stands still');
    assertEq(c.done(200000), false, 'a paused countdown never ends');
    c.resume(50000);
    assertEq(c.remaining(60000), 20000, 'resumed');
    assertEq(c.done(80000), true, 'ends');
    assertEq(c.remaining(90000), 0, 'never negative');
    assertEq(Math.round(new Countdown(1000, 0).progress(250) * 100), 25, 'progress');
});

test('downloads in progress are recognised by their temporary names', () => {
    assertEq(partialDownload('report.pdf.crdownload'), 'report.pdf', 'Chromium');
    assertEq(partialDownload('photo.jpg.part'), 'photo.jpg', 'Firefox');
    assertEq(partialDownload('Unconfirmed 812345.crdownload'), '', 'Chromium before the name is known');
    assertEq(partialDownload('notes.txt'), null, 'a finished file');
    assertEq(partialDownload('.part'), null, 'not a name');
    assertEq(partialDownload('ISO.DOWNLOAD'), 'ISO', 'any case');
});

test('apps using the microphone, as GNOME counts them', () => {
    assertEq(microphoneUsers([{id: 'org.gnome.VolumeControl', name: 'Sound'}, {id: 'com.zoom', name: 'Zoom'},
        {id: 'com.zoom', name: 'Zoom'}, {id: 'org.mozilla.firefox', name: 'Firefox'}]), ['Zoom', 'Firefox'],
    'volume meters ignored, each app once');
    assertEq(microphoneUsers([{id: 'org.PulseAudio.pavucontrol', name: 'Volume'}]), [], 'only meters: none');
    assertEq(microphoneUsers([{id: '', name: ''}]), ['An app'], 'an unnamed recorder still counts');
});

test('network changes worth telling', () => {
    const wifi = {connected: true, name: 'Home', wifi: true};
    assertEq(networkChange(null, wifi), null, 'not at startup');
    assertEq(networkChange({connected: false}, wifi).text, 'Connected', 'connected');
    assertEq(networkChange({connected: false}, wifi).icon, 'network-wireless-symbolic', 'Wi-Fi icon');
    assertEq(networkChange({connected: true, name: 'Home', wifi: true}, {connected: true, name: 'Office',
        wifi: false}).detail, 'Office', 'switched networks');
    assertEq(networkChange(wifi, {connected: false}).text, 'Offline', 'lost');
    assertEq(networkChange(wifi, wifi), null, 'no change');
    assertEq(networkChange({connected: false}, {connected: false}), null, 'still offline');
});

test('the activity settings cover every activity kind', () => {
    const covered = new Set(Object.values(ACTIVITY_GROUPS).flat());
    assertEq(Object.keys(PRIORITY).filter(k => !covered.has(k)), [], 'every kind can be turned off');
    assertEq([...allowedKinds(['timers', 'bogus'])].sort(), ['stopwatch', 'timer', 'timer-done'], 'unknown ids ignored');
    assertEq(notificationCount(1), '1 notification', 'one');
    assertEq(notificationCount(3), '3 notifications', 'more');
    assertEq(WIDGETS.includes('timer'), true, 'the timer widget');
});

test('a minute more on a timer, running or paused', () => {
    const c = new Countdown(60000, 0);
    c.add(60000, 10000);
    assertEq(c.remaining(10000), 110000, 'running: a minute more left');
    c.pause(20000);
    c.add(60000, 30000);
    assertEq(c.remaining(99999), 160000, 'paused: added to the time kept');
    assertEq(c.duration, 180000, 'the bar measures the whole time');
});

test('the new activities can be turned off, and glimpses end', () => {
    assertEq([...allowedKinds(['do-not-disturb', 'workspaces'])].sort(), ['dnd', 'workspace'], 'new groups');
    assertEq(allowedKinds(['levels']).has('mic'), true, 'microphone mute with the levels');
    assertEq(allowedKinds(['keyboard']).has('input-source'), true, 'keyboard layout with Caps Lock');
    for (const kind of ['mic', 'input-source', 'workspace'])
        assertEq(GLIMPSE_MS[kind] > 0, true, `${kind} is a glimpse`);
    assertEq(PRIORITY.dnd < PRIORITY['stay-awake'], true, 'Do Not Disturb is the quietest ongoing');
});

test('dynamic colors follow what is going on', () => {
    const accent = ACCENTS.green;
    assertEq(tintFor('recording', {}, 'dynamic', accent), TINTS.recording, 'recording is red');
    assertEq(tintFor('timer', {focus: true}, 'dynamic', accent), TINTS.focus, 'a focus session, not a timer');
    assertEq(tintFor('media', {color: [1, 2, 3]}, 'dynamic', accent), [1, 2, 3], 'the album color wins');
    assertEq(tintFor('media', {}, 'dynamic', accent), TINTS.media, 'music without art');
    assertEq(tintFor('notification', {}, 'dynamic', accent), accent, 'notifications in the accent');
    assertEq(tintFor('level', {}, 'dynamic', accent), null, 'volume stays neutral');
    assertEq(tintFor('recording', {}, 'accent', accent), accent, 'accent mode');
    assertEq(tintFor('level', {}, 'accent', accent), null, 'accent mode keeps neutral things neutral');
    assertEq(tintFor('recording', {}, 'neutral', accent), null, 'neutral mode');
    assertEq(tintKey('idle', {glance: 'weather'}), 'weather', 'the idle glance has its color');
    assertEq(tintKey('network', {offline: true}), 'offline', 'offline is grey');
    assertEq(tintStyle(null), '', 'no style without a color');
    assertEq(tintStyle([10, 20, 30]).includes('rgba(10, 20, 30, 0.24)'), true, 'translucent background');
});

test('the color of album art', () => {
    const image = (w, h, rgb) => {
        const px = new Uint8Array(w * h * 3);
        for (let i = 0; i < w * h; i++)
            px.set(rgb(i), i * 3);
        return px;
    };
    assertEq(dominantColor(image(4, 4, () => [128, 128, 128]), 4, 4, 12, 3), null, 'grey art: no color');
    const red = dominantColor(image(4, 4, i => i < 4 ? [220, 30, 30] : [20, 20, 20]), 4, 4, 12, 3);
    assertEq(red[0] > 150 && red[1] < 60 && red[2] < 60, true, `a red cover is red (${red})`);
    const dark = dominantColor(image(2, 2, () => [60, 10, 90]), 2, 2, 6, 3);
    assertEq(Math.max(...dark) >= 170, true, `a dark color is lifted to read as a color (${dark})`);
});

print(`1..${count}`);
if (failures > 0) {
    printerr(`${failures} of ${count} tests failed`);
    System.exit(1);
}
