// SPDX-License-Identifier: GPL-3.0-or-later
//
// What the Wi-Fi status icon shows (wifi-indicator.js), without Shell
// imports (unit-tested with plain gjs: tests/unit/js/test_wifi_model.js).

import NM from 'gi://NM';

/** GNOME's signal levels (status/network.js), so both icons agree. */
export function signalLevel(strength) {
    if (strength < 20)
        return 'none';
    if (strength < 40)
        return 'weak';
    if (strength < 50)
        return 'ok';
    if (strength < 80)
        return 'good';
    return 'excellent';
}

const CONNECTING = new Set([NM.DeviceState.PREPARE, NM.DeviceState.CONFIG, NM.DeviceState.NEED_AUTH,
    NM.DeviceState.IP_CONFIG, NM.DeviceState.IP_CHECK, NM.DeviceState.SECONDARIES]);

/**
 * What to show for Wi-Fi: {icon, visible}. Pure, for tests: adapter is
 * {state, strength} of the Wi-Fi device (or null without one).
 */
export function wifiIcon(adapter, {radioOn = true, primaryIsWifi = false} = {}) {
    if (!adapter || primaryIsWifi)
        return {icon: null, visible: false};
    if (!radioOn || adapter.state === NM.DeviceState.UNAVAILABLE)
        return {icon: 'network-wireless-disabled-symbolic', visible: true};
    if (adapter.state === NM.DeviceState.ACTIVATED)
        return {icon: `network-wireless-signal-${signalLevel(adapter.strength ?? 0)}-symbolic`, visible: true};
    if (CONNECTING.has(adapter.state))
        return {icon: 'network-wireless-acquiring-symbolic', visible: true};
    return {icon: 'network-wireless-offline-symbolic', visible: true};
}
