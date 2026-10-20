// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Start menu's pinned apps: an ordered list of desktop IDs kept in the
// 'start-pinned-apps' setting, separate from the taskbar's pins (GNOME's
// favorites), as in Windows 11. Every function returns a new list and
// never changes its argument. No GNOME Shell imports, so it is unit-tested
// with plain gjs (tests/unit/js/test_start_pins.js).

/** ids without duplicates or empty entries, first occurrence kept. */
export function normalize(ids) {
    const seen = new Set();
    return ids.filter(id => {
        if (typeof id !== 'string' || !id || seen.has(id))
            return false;
        seen.add(id);
        return true;
    });
}

export function isPinned(ids, id) {
    return ids.includes(id);
}

/** Pins id at the end (or at index), or leaves the list as it is if pinned. */
export function pin(ids, id, index = Infinity) {
    const list = normalize(ids);
    if (!id || list.includes(id))
        return list;
    const at = Math.max(0, Math.min(list.length, index));
    list.splice(at, 0, id);
    return list;
}

export function unpin(ids, id) {
    return normalize(ids).filter(i => i !== id);
}

/** Moves a pinned id to index (clamped); unpinned ids are not added. */
export function move(ids, id, index) {
    const list = normalize(ids);
    const from = list.indexOf(id);
    if (from < 0)
        return list;
    list.splice(from, 1);
    const at = Math.max(0, Math.min(list.length, index));
    list.splice(at, 0, id);
    return list;
}

/** Pinned ids whose apps are installed, in pinned order. */
export function available(ids, isInstalled) {
    return normalize(ids).filter(id => isInstalled(id));
}

/**
 * Index in the full list for a move among the visible (installed) pins
 * only, so uninstalled pins keep their places: moving to visible index i
 * puts the app where the i-th visible pin is now. Meant for move(), which
 * takes the index after the moved app has been removed.
 */
export function visibleToFullIndex(ids, visible, visibleIndex) {
    const list = normalize(ids);
    if (visibleIndex <= 0)
        return visible.length ? list.indexOf(visible[0]) : 0;
    if (visibleIndex >= visible.length)
        return list.length;
    return list.indexOf(visible[visibleIndex]);
}
