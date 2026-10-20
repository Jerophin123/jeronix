// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Control Center's model: which modules exist, their sizes on the
// 4-column grid, and how the enabled ones are packed. No GNOME Shell
// imports, so it is unit-tested with plain gjs (tests/unit/js/test_cc_model.js).

export const COLUMNS = 4;

// Rows of the connectivity module (macOS: the Wi-Fi / Bluetooth / AirDrop
// card). Enabled ones share one card, placed where the first one is listed.
export const CONNECTIVITY = ['wifi', 'bluetooth', 'airplane-mode', 'vpn'];

// Every module: [id, width, height] on the grid (connectivity rows have no
// size of their own). The order is the default order.
export const MODULES = [
    ['wifi', 0, 0],
    ['bluetooth', 0, 0],
    ['airplane-mode', 0, 0],
    ['vpn', 0, 0],
    ['focus', 2, 1],
    ['stay-awake', 2, 1],
    ['dark-mode', 1, 1],
    ['night-light', 1, 1],
    ['power-mode', 2, 1],
    ['display', 4, 1],
    ['sound', 4, 1],
    ['now-playing', 4, 1],
    ['battery', 2, 1],
    ['screenshot', 1, 1],
    ['screen-recording', 1, 1],
    ['settings', 2, 1],
];

export const MODULE_IDS = MODULES.map(([id]) => id);

const SIZES = new Map(MODULES.map(([id, w, h]) => [id, [w, h]]));

/**
 * The blocks to show, in order: [{id, w, h, rows?}]. enabled is the user's
 * ordered list; available(id) says whether this computer has the module
 * (no Bluetooth adapter, no battery...). Unknown and duplicate ids are
 * ignored. The connectivity rows become one 2-wide block, one grid row
 * tall per two rows.
 */
export function blocks(enabled, available) {
    const seen = new Set();
    const result = [];
    let connectivity = null;
    for (const id of enabled) {
        if (!SIZES.has(id) || seen.has(id))
            continue;
        seen.add(id);
        if (!available(id))
            continue;
        if (CONNECTIVITY.includes(id)) {
            if (!connectivity) {
                connectivity = {id: 'connectivity', w: 2, h: 1, rows: []};
                result.push(connectivity);
            }
            connectivity.rows.push(id);
            connectivity.h = Math.ceil(connectivity.rows.length / 2);
        } else {
            const [w, h] = SIZES.get(id);
            result.push({id, w, h});
        }
    }
    return result;
}

/**
 * Places blocks on a grid of `columns` columns, first fit, row by row: each
 * block goes to the first free spot where it fits, so small modules fill
 * the gaps beside larger ones and no holes are left where possible.
 * Returns new objects with col and row.
 */
export function pack(items, columns = COLUMNS) {
    const taken = [];
    const free = (col, row, w, h) => {
        for (let r = row; r < row + h; r++) {
            for (let c = col; c < col + w; c++) {
                if (taken[r]?.[c])
                    return false;
            }
        }
        return true;
    };
    return items.map(item => {
        const w = Math.max(1, Math.min(columns, item.w));
        const h = Math.max(1, item.h);
        for (let row = 0; ; row++) {
            for (let col = 0; col + w <= columns; col++) {
                if (!free(col, row, w, h))
                    continue;
                for (let r = row; r < row + h; r++) {
                    taken[r] ??= [];
                    for (let c = col; c < col + w; c++)
                        taken[r][c] = true;
                }
                return {...item, w, h, col, row};
            }
        }
    });
}

// 802.11 flags (libnm NM80211ApFlags / NM80211ApSecurityFlags).
const AP_PRIVACY = 0x1;
const KEY_MGMT_PSK = 0x100;
const KEY_MGMT_802_1X = 0x200;
const KEY_MGMT_SAE = 0x400;

/** Whether joining needs a password (open and OWE networks do not). */
export function needsPassword(flags, wpaFlags, rsnFlags) {
    const security = wpaFlags | rsnFlags;
    const wep = (flags & AP_PRIVACY) !== 0 && security === 0;
    return wep || (security & (KEY_MGMT_PSK | KEY_MGMT_SAE | KEY_MGMT_802_1X)) !== 0;
}

/** One entry per network name (the strongest), strongest first; hidden networks dropped. */
export function networks(points) {
    const best = new Map();
    for (const p of points) {
        if (!p.ssid)
            continue;
        if (!best.has(p.ssid) || p.strength > best.get(p.ssid).strength)
            best.set(p.ssid, p);
    }
    return [...best.values()].sort((a, b) => b.strength - a.strength || a.ssid.localeCompare(b.ssid));
}

/** Signal icon for a 0..100 strength. */
export function signalIcon(strength) {
    if (strength >= 75)
        return 'network-wireless-signal-excellent-symbolic';
    if (strength >= 50)
        return 'network-wireless-signal-good-symbolic';
    if (strength >= 25)
        return 'network-wireless-signal-ok-symbolic';
    return 'network-wireless-signal-weak-symbolic';
}

/** "3 h 20 min" / "45 min" for a number of seconds; '' for 0. */
export function duration(seconds) {
    if (!seconds || seconds < 60)
        return '';
    const minutes = Math.round(seconds / 60);
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (!h)
        return `${m} min`;
    return m ? `${h} h ${m} min` : `${h} h`;
}
