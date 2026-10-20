// SPDX-License-Identifier: GPL-3.0-or-later
// Run: gjs -m tests/unit/js/test_wifi_model.js

import NM from 'gi://NM';
import System from 'system';

import {signalLevel, wifiIcon} from '../../../desktop/extensions/jeronix-quick-settings/wifi-model.js';

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

test('signal levels match GNOME', () => {
    assertEq([0, 19, 20, 39, 40, 49, 50, 79, 80, 100].map(signalLevel),
        ['none', 'none', 'weak', 'weak', 'ok', 'ok', 'good', 'good', 'excellent', 'excellent'], 'levels');
});

test('Wi-Fi shows whenever there is an adapter', () => {
    assertEq(wifiIcon(null), {icon: null, visible: false}, 'no adapter: nothing');
    assertEq(wifiIcon({state: NM.DeviceState.ACTIVATED, strength: 65}),
        {icon: 'network-wireless-signal-good-symbolic', visible: true}, 'connected: its signal');
    assertEq(wifiIcon({state: NM.DeviceState.ACTIVATED}).icon, 'network-wireless-signal-none-symbolic',
        'connected, strength not known yet');
    assertEq(wifiIcon({state: NM.DeviceState.CONFIG}).icon, 'network-wireless-acquiring-symbolic', 'connecting');
    assertEq(wifiIcon({state: NM.DeviceState.DISCONNECTED}).icon, 'network-wireless-offline-symbolic',
        'disconnected (a cable in use)');
    assertEq(wifiIcon({state: NM.DeviceState.DISCONNECTED}, {radioOn: false}).icon,
        'network-wireless-disabled-symbolic', 'Wi-Fi switched off');
    assertEq(wifiIcon({state: NM.DeviceState.ACTIVATED, strength: 90}, {primaryIsWifi: true}).visible, false,
        "the primary connection: GNOME's own icon shows it");
});

print(`1..${count}`);
if (failures)
    System.exit(1);
