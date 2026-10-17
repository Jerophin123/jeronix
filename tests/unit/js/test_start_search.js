// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_start_search.js

import System from 'system';

import {alphabetical, score, search} from '../../../desktop/extensions/jeronix-dock/search.js';

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

const apps = [
    {name: 'Text Editor', keywords: ['notepad'], generic: 'Text Editor', executable: 'gnome-text-editor'},
    {name: 'Terminal', keywords: ['shell', 'prompt'], executable: 'ptyxis'},
    {name: 'Firefox Web Browser', generic: 'Web Browser', description: 'Browse the World Wide Web'},
    {name: 'Settings', keywords: ['preferences']},
];

test('name prefixes rank first, ties alphabetical', () => {
    // Terminal and Text Editor start with "t" (100), "Settings" contains it
    // (60), Firefox only matches in its description (20).
    assertEq(search(apps, 't').map(a => a.name), ['Terminal', 'Text Editor', 'Settings', 'Firefox Web Browser'],
        'order');
});

test('keywords, generic names and executables match', () => {
    assertEq(search(apps, 'notepad')[0].name, 'Text Editor', 'keyword');
    assertEq(search(apps, 'ptyxis')[0].name, 'Terminal', 'executable');
    assertEq(search(apps, 'preferences')[0].name, 'Settings', 'keyword');
});

test('every word must match', () => {
    assertEq(search(apps, 'web browser').map(a => a.name), ['Firefox Web Browser'], 'two words');
    assertEq(search(apps, 'web terminal'), [], 'no app has both');
});

test('empty query scores zero and case is ignored', () => {
    assertEq(score(apps[0], ''), 0, 'empty');
    assertEq(score(apps[1], 'TERM') > 0, true, 'case');
});

test('alphabetical view', () => {
    assertEq(alphabetical(apps).map(a => a.name)[0], 'Firefox Web Browser', 'first');
});

print(`1..${count}`);
if (failures > 0) {
    printerr(`${failures} of ${count} tests failed`);
    System.exit(1);
}
