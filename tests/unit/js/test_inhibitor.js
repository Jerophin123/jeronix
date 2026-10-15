// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_inhibitor.js

import System from 'system';

import {Inhibitor, InhibitFlags} from '../../../desktop/extensions/jeronix-quick-settings/inhibitor.js';

let failures = 0;
let count = 0;

function assertEq(actual, expected, what) {
    if (JSON.stringify(actual) !== JSON.stringify(expected))
        throw new Error(`${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

async function test(name, fn) {
    count++;
    try {
        await fn();
        print(`ok - ${name}`);
    } catch (e) {
        failures++;
        print(`FAIL - ${name}: ${e.message}`);
    }
}

// Fake client whose calls stay pending until release() is called, so tests
// control the interleaving of overlapping requests.
class FakeClient {
    constructor({failInhibit = false, failUninhibit = false} = {}) {
        this.failInhibit = failInhibit;
        this.failUninhibit = failUninhibit;
        this.calls = [];
        this.held = new Set();
        this._queue = [];
        this._next = 100;
    }

    inhibit(appId, reason, flags) {
        this.calls.push(['inhibit', appId, flags]);
        return this._defer(() => {
            if (this.failInhibit)
                throw new Error('no session manager');
            const cookie = this._next++;
            this.held.add(cookie);
            return cookie;
        });
    }

    uninhibit(cookie) {
        this.calls.push(['uninhibit', cookie]);
        return this._defer(() => {
            if (this.failUninhibit)
                throw new Error('uninhibit refused');
            this.held.delete(cookie);
        });
    }

    _defer(fn) {
        return new Promise((resolve, reject) => {
            this._queue.push(() => {
                try {
                    resolve(fn());
                } catch (e) {
                    reject(e);
                }
            });
        });
    }

    // Answer queued calls until none remain, letting continuations run.
    async drain() {
        for (let i = 0; i < 50; i++) {
            await null;
            const next = this._queue.shift();
            if (next)
                next();
        }
    }
}

function make(client, events = []) {
    return new Inhibitor(client, {
        appId: 'test@jeronix',
        reason: 'test',
        flags: InhibitFlags.IDLE | InhibitFlags.SUSPEND,
        onChanged: (active, error) => events.push([active, error?.message ?? null]),
    });
}

await test('enable acquires one cookie with idle|suspend flags', async () => {
    const client = new FakeClient();
    const events = [];
    const inh = make(client, events);
    inh.enable();
    await client.drain();
    assertEq(inh.active, true, 'active');
    assertEq(client.calls, [['inhibit', 'test@jeronix', 12]], 'calls');
    assertEq(events, [[true, null]], 'events');
});

await test('disable releases the cookie it acquired', async () => {
    const client = new FakeClient();
    const inh = make(client);
    inh.enable();
    await client.drain();
    inh.disable();
    await client.drain();
    assertEq(inh.active, false, 'active');
    assertEq(client.held.size, 0, 'held cookies');
});

await test('repeated enable does not stack inhibitions', async () => {
    const client = new FakeClient();
    const inh = make(client);
    inh.enable();
    inh.enable();
    await client.drain();
    inh.enable();
    await client.drain();
    assertEq(client.held.size, 1, 'held cookies');
});

await test('disable while inhibit is in flight releases it afterwards', async () => {
    const client = new FakeClient();
    const inh = make(client);
    inh.enable();
    inh.disable();
    await client.drain();
    assertEq(inh.active, false, 'active');
    assertEq(client.held.size, 0, 'held cookies');
    assertEq(client.calls.map(c => c[0]), ['inhibit', 'uninhibit'], 'call order');
});

await test('failed inhibit reports error and stays inactive', async () => {
    const client = new FakeClient({failInhibit: true});
    const events = [];
    const inh = make(client, events);
    inh.enable();
    await client.drain();
    assertEq(inh.active, false, 'active');
    assertEq(inh.wanted, false, 'wanted');
    assertEq(events, [[false, 'no session manager']], 'events');
});

await test('failed uninhibit does not wedge the inhibitor', async () => {
    const client = new FakeClient({failUninhibit: true});
    const events = [];
    const inh = make(client, events);
    inh.enable();
    await client.drain();
    inh.disable();
    await client.drain();
    assertEq(inh.active, false, 'active');
    assertEq(events[1], [false, 'uninhibit refused'], 'error event');
    client.failUninhibit = false;
    inh.enable();
    await client.drain();
    assertEq(inh.active, true, 're-enabled');
});

await test('destroy releases the cookie and silences callbacks', async () => {
    const client = new FakeClient();
    const events = [];
    const inh = make(client, events);
    inh.enable();
    await client.drain();
    inh.destroy();
    await client.drain();
    assertEq(client.held.size, 0, 'held cookies');
    assertEq(events.length, 1, 'no events after destroy');
    inh.enable();
    await client.drain();
    assertEq(client.held.size, 0, 'enable after destroy is ignored');
});

await test('destroy during in-flight inhibit still releases', async () => {
    const client = new FakeClient();
    const inh = make(client);
    inh.enable();
    inh.destroy();
    await client.drain();
    assertEq(client.held.size, 0, 'held cookies');
});

print(`1..${count}`);
if (failures > 0) {
    printerr(`${failures} of ${count} tests failed`);
    System.exit(1);
}
