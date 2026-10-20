// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_cc_model.js

import System from 'system';

import {COLUMNS, MODULE_IDS, blocks, duration, needsPassword, networks, pack, signalIcon}
    from '../../../desktop/extensions/jeronix-dock/cc-model.js';

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

const all = () => true;
const place = items => pack(items).map(({id, col, row, w, h}) => [id, col, row, w, h]);

test('connectivity rows share one card where the first is listed', () => {
    const b = blocks(['focus', 'bluetooth', 'wifi', 'vpn'], all);
    assertEq(b.map(x => x.id), ['focus', 'connectivity'], 'ids');
    assertEq(b[1].rows, ['bluetooth', 'wifi', 'vpn'], 'rows in the given order');
    assertEq([b[1].w, b[1].h], [2, 2], 'three rows are two grid rows tall');
});

test('unavailable, unknown and duplicate modules are left out', () => {
    const b = blocks(['wifi', 'bluetooth', 'nope', 'focus', 'focus', 'battery'],
        id => id !== 'bluetooth' && id !== 'battery');
    assertEq(b.map(x => x.id), ['connectivity', 'focus'], 'ids');
    assertEq([b[0].rows, b[0].h], [['wifi'], 1], 'one row, one grid row');
    assertEq(blocks(['bluetooth'], () => false), [], 'nothing available');
});

test('the default layout fills the grid without holes', () => {
    const placed = place(blocks(MODULE_IDS, all));
    assertEq(placed, [
        ['connectivity', 0, 0, 2, 2],
        ['focus', 2, 0, 2, 1],
        ['stay-awake', 2, 1, 2, 1],
        ['dark-mode', 0, 2, 1, 1],
        ['night-light', 1, 2, 1, 1],
        ['power-mode', 2, 2, 2, 1],
        ['display', 0, 3, 4, 1],
        ['sound', 0, 4, 4, 1],
        ['now-playing', 0, 5, 4, 1],
        ['battery', 0, 6, 2, 1],
        ['screenshot', 2, 6, 1, 1],
        ['screen-recording', 3, 6, 1, 1],
        ['settings', 0, 7, 2, 1],
    ], 'positions');
});

test('a desktop without Wi-Fi, Bluetooth or battery still packs tightly', () => {
    const missing = new Set(['wifi', 'bluetooth', 'airplane-mode', 'battery', 'display']);
    const placed = place(blocks(MODULE_IDS, id => !missing.has(id)));
    assertEq(placed.slice(0, 4), [
        ['connectivity', 0, 0, 2, 1],
        ['focus', 2, 0, 2, 1],
        ['stay-awake', 0, 1, 2, 1],
        ['dark-mode', 2, 1, 1, 1],
    ], 'first rows');
    const filled = [];
    for (const [, col, row, w, h] of placed) {
        for (let r = row; r < row + h; r++)
            filled[r] = (filled[r] ?? 0) + w;
    }
    const last = filled.length - 1;
    assertEq(filled.slice(0, last).every(n => n === COLUMNS), true, `no holes before the last row ${filled}`);
});

test('small modules fill gaps left by larger ones', () => {
    assertEq(place([{id: 'a', w: 2, h: 1}, {id: 'b', w: 4, h: 1}, {id: 'c', w: 1, h: 1}]),
        [['a', 0, 0, 2, 1], ['b', 0, 1, 4, 1], ['c', 2, 0, 1, 1]], 'c goes beside a');
    assertEq(place([{id: 'wide', w: 9, h: 1}]), [['wide', 0, 0, 4, 1]], 'width clamped to the grid');
});

test('which networks need a password', () => {
    assertEq(needsPassword(0, 0, 0), false, 'open');
    assertEq(needsPassword(0, 0, 0x800 | 0x8), false, 'OWE');
    assertEq(needsPassword(1, 0, 0x100 | 0x8), true, 'WPA2');
    assertEq(needsPassword(1, 0, 0x400 | 0x8), true, 'WPA3');
    assertEq(needsPassword(1, 0, 0x200 | 0x8), true, 'enterprise');
    assertEq(needsPassword(1, 0, 0), true, 'WEP');
});

test('networks: strongest per name, hidden dropped, strongest first', () => {
    const list = networks([
        {ssid: 'Home', strength: 40}, {ssid: 'Home', strength: 80}, {ssid: null, strength: 99},
        {ssid: 'cafe', strength: 80}, {ssid: 'Attic', strength: 10},
    ]);
    assertEq(list.map(n => [n.ssid, n.strength]), [['cafe', 80], ['Home', 80], ['Attic', 10]], 'list');
    assertEq(signalIcon(90), 'network-wireless-signal-excellent-symbolic', 'excellent');
    assertEq(signalIcon(5), 'network-wireless-signal-weak-symbolic', 'weak');
});

test('battery time', () => {
    assertEq(duration(0), '', 'none');
    assertEq(duration(45 * 60), '45 min', 'minutes');
    assertEq(duration(2 * 3600), '2 h', 'hours');
    assertEq(duration(3 * 3600 + 20 * 60), '3 h 20 min', 'both');
});

print(`${count - failures}/${count} passed`);
if (failures)
    System.exit(1);
