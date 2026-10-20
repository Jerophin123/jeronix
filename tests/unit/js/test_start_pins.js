// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_start_pins.js

import System from 'system';

import {available, isPinned, move, normalize, pin, unpin, visibleToFullIndex}
    from '../../../desktop/extensions/jeronix-dock/pins.js';

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

const PINS = ['files.desktop', 'terminal.desktop', 'editor.desktop'];

test('normalize drops duplicates and empty entries', () => {
    assertEq(normalize(['a', '', 'b', 'a', null, 'c']), ['a', 'b', 'c'], 'normalized');
});

test('pin appends, or inserts at an index', () => {
    assertEq(pin(PINS, 'calc.desktop'), [...PINS, 'calc.desktop'], 'appended');
    assertEq(pin(PINS, 'calc.desktop', 0), ['calc.desktop', ...PINS], 'at front');
    assertEq(pin(PINS, 'calc.desktop', 99), [...PINS, 'calc.desktop'], 'index clamped');
});

test('pinning a pinned app changes nothing', () => {
    assertEq(pin(PINS, 'terminal.desktop'), PINS, 'unchanged');
});

test('pin, unpin and move never modify their argument', () => {
    const before = [...PINS];
    pin(PINS, 'x.desktop');
    unpin(PINS, 'files.desktop');
    move(PINS, 'editor.desktop', 0);
    assertEq(PINS, before, 'argument');
});

test('unpin removes only that app', () => {
    assertEq(unpin(PINS, 'terminal.desktop'), ['files.desktop', 'editor.desktop'], 'unpinned');
    assertEq(unpin(PINS, 'missing.desktop'), PINS, 'missing app');
});

test('isPinned', () => {
    assertEq(isPinned(PINS, 'editor.desktop'), true, 'pinned');
    assertEq(isPinned(PINS, 'calc.desktop'), false, 'not pinned');
});

test('move reorders pinned apps and ignores unpinned ones', () => {
    assertEq(move(PINS, 'editor.desktop', 0), ['editor.desktop', 'files.desktop', 'terminal.desktop'], 'to front');
    assertEq(move(PINS, 'files.desktop', 99), ['terminal.desktop', 'editor.desktop', 'files.desktop'], 'to end');
    assertEq(move(PINS, 'calc.desktop', 0), PINS, 'unpinned app');
});

test('available keeps installed apps in pinned order', () => {
    const installed = new Set(['editor.desktop', 'files.desktop']);
    assertEq(available(PINS, id => installed.has(id)), ['files.desktop', 'editor.desktop'], 'available');
});

test('moves among visible pins keep uninstalled pins in place', () => {
    const all = ['a', 'gone', 'b', 'c'];
    const visible = ['a', 'b', 'c'];
    const to = (id, i) => move(all, id, visibleToFullIndex(all, visible, i));
    assertEq(to('c', 0), ['c', 'a', 'gone', 'b'], 'c to front');
    assertEq(to('a', 3), ['gone', 'b', 'c', 'a'], 'a to end');
    assertEq(to('c', 1), ['a', 'gone', 'c', 'b'], 'c one left');
    assertEq(to('a', 1), ['gone', 'b', 'a', 'c'], 'a one right');
    assertEq(visibleToFullIndex(all, [], 0), 0, 'no visible pins');
});

print(`${count - failures}/${count} passed`);
if (failures)
    System.exit(1);
