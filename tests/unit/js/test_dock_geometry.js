// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_dock_geometry.js

import System from 'system';

import {Geometry, MARGIN, ITEM_PADDING, fitIconSize, dropIndex, taskbarRow, TRAY_GAP} from
    '../../../desktop/extensions/jeronix-dock/geometry.js';

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

const monitor = {x: 0, y: 0, width: 1600, height: 1000};
const second = {x: 1600, y: 0, width: 1920, height: 1080};

test('bottom dock is centered with the margin below it', () => {
    const g = new Geometry('bottom', monitor, 32);
    assertEq(g.place(400, 76), {x: 600, y: 1000 - 76 - MARGIN, width: 400, height: 76 + MARGIN}, 'rect');
});

test('left and right docks center in the space below the top bar', () => {
    const left = new Geometry('left', monitor, 32).place(76, 300);
    assertEq(left, {x: 0, y: 32 + (1000 - 32 - 300) / 2, width: 76 + MARGIN, height: 300}, 'left');
    const right = new Geometry('right', monitor, 32).place(76, 300);
    assertEq(right.x + right.width, 1600, 'right edge flush with the monitor');
});

test('placement follows a monitor that is not at the origin', () => {
    const r = new Geometry('bottom', second, 32).place(400, 76);
    assertEq([r.x, r.y + r.height], [1600 + (1920 - 400) / 2, 1080], 'second monitor');
});

test('edge strips sit on the screen edge the dock hides behind', () => {
    const g = new Geometry('bottom', monitor, 32);
    const rect = g.place(400, 76);
    assertEq(g.edgeStrip(rect), {x: 600, y: 998, width: 400, height: 2}, 'bottom strip');
    const l = new Geometry('left', monitor, 32);
    assertEq(l.edgeStrip(l.place(76, 300)).x, 0, 'left strip');
});

test('hidden offsets move the dock fully off screen', () => {
    const g = new Geometry('bottom', monitor, 32);
    const rect = g.place(400, 76);
    assertEq(g.hiddenOffset(rect), {x: 0, y: rect.height}, 'bottom');
    const l = new Geometry('left', monitor, 32);
    assertEq(l.hiddenOffset(l.place(76, 300)).x, -(76 + MARGIN), 'left');
});

test('the full-width taskbar spans the bottom edge of its monitor', () => {
    const g = new Geometry('bottom', second, 0);
    assertEq(g.placeTaskbar(48), {x: 1600, y: 1080 - 48, width: 1920, height: 48}, 'rect');
    assertEq(g.hiddenOffset(g.placeTaskbar(48)), {x: 0, y: 48}, 'hides downward');
    assertEq(g.taskbarAvailable(300) < 1920 - 600, true, 'tray width kept free on both sides');
    let threw = false;
    try {
        new Geometry('left', monitor, 32).placeTaskbar(48);
    } catch {
        threw = true;
    }
    assertEq(threw, true, 'only at the bottom');
});

test('unknown positions are rejected', () => {
    let threw = false;
    try {
        new Geometry('top', monitor, 32);
    } catch {
        threw = true;
    }
    assertEq(threw, true, 'top is not a dock position');
});

test('icons keep their preferred size when everything fits', () => {
    assertEq(fitIconSize({items: 8, extras: 1, preferred: 44, minimum: 24, available: 1500}),
        {iconSize: 44, overflow: false, itemsLength: -1}, 'fit');
});

test('icons shrink in 4 px steps until they fit', () => {
    const r = fitIconSize({items: 20, extras: 1, preferred: 48, minimum: 24, available: 1000});
    assertEq(r.overflow, false, 'fits after shrinking');
    assertEq(21 * (r.iconSize + ITEM_PADDING) <= 1000, true, 'length within available');
    assertEq(21 * (r.iconSize + 4 + ITEM_PADDING) > 1000, true, 'largest size that fits');
});

test('too many apps scroll at the minimum size, keeping room for the apps button', () => {
    const r = fitIconSize({items: 60, extras: 1, preferred: 48, minimum: 24, available: 1000});
    assertEq(r.iconSize, 24, 'minimum');
    assertEq(r.overflow, true, 'overflow');
    assertEq(r.itemsLength + (24 + ITEM_PADDING) <= 1000, true, 'items area + apps button fit');
    assertEq(r.itemsLength % (24 + ITEM_PADDING), 0, 'whole items only');
});

test('drop index is the insertion point between item centers', () => {
    const centers = [30, 90, 150];
    assertEq(dropIndex(centers, 0), 0, 'before first');
    assertEq(dropIndex(centers, 60), 1, 'between first and second');
    assertEq(dropIndex(centers, 400), 3, 'after last');
    assertEq(dropIndex([], 10), 0, 'empty dock');
});

test('the taskbar group is centered on the whole bar whatever the tray width', () => {
    for (const trayWidth of [0, 120, 260]) {
        const r = taskbarRow({width: 1600, groupWidth: 500, trayWidth, centered: true});
        assertEq(r.groupX + r.groupWidth / 2, 800, `centered with a ${trayWidth}px tray`);
        assertEq(r.trayX, 1600 - trayWidth, 'tray at the right end');
    }
});

test('a wide group moves left of the tray instead of overlapping it', () => {
    const r = taskbarRow({width: 1000, groupWidth: 700, trayWidth: 200, centered: true});
    assertEq(r.groupX + r.groupWidth <= r.trayX - TRAY_GAP, true, 'no overlap');
    assertEq(r.groupX, 1000 - 200 - TRAY_GAP - 700, 'pushed left just enough');
    const tight = taskbarRow({width: 600, groupWidth: 700, trayWidth: 200, centered: true});
    assertEq(tight.groupX, 0, 'starts at the left edge');
    assertEq(tight.groupWidth, 600 - 200 - TRAY_GAP, 'clipped to the space left of the tray');
});

test('a left-aligned group starts at the left edge', () => {
    const r = taskbarRow({width: 1600, groupWidth: 500, trayWidth: 200, centered: false});
    assertEq(r.groupX, 0, 'start');
    assertEq(r.trayX, 1400, 'tray');
});

print(`1..${count}`);
if (failures > 0) {
    printerr(`${failures} of ${count} tests failed`);
    System.exit(1);
}
