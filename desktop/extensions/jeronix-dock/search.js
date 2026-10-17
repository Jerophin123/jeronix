// SPDX-License-Identifier: GPL-3.0-or-later
//
// App search ranking for the Start menu. No GNOME Shell imports, so it is
// unit-tested with plain gjs (tests/unit/js/test_start_search.js). Same
// rules as the JERONIX Launcher (apps/launcher/catalog.py).

function scoreToken(entry, token) {
    const name = entry.name.toLowerCase();
    if (name.startsWith(token))
        return 100;
    if (name.split(/\s+/).some(w => w.startsWith(token)))
        return 80;
    if (name.includes(token))
        return 60;
    const others = [entry.generic ?? '', entry.executable ?? '', ...(entry.keywords ?? [])];
    if (others.some(o => o && o.toLowerCase().includes(token)))
        return 40;
    if ((entry.description ?? '').toLowerCase().includes(token))
        return 20;
    return null;
}

/** Relevance of entry for query, or null. Every word must match. */
export function score(entry, query) {
    const tokens = query.toLowerCase().split(/\s+/).filter(t => t);
    if (tokens.length === 0)
        return 0;
    let total = 0;
    for (const token of tokens) {
        const s = scoreToken(entry, token);
        if (s === null)
            return null;
        total += s;
    }
    return total;
}

/** Matching entries, best first, then alphabetical. */
export function search(entries, query) {
    return entries
        .map(entry => ({entry, s: score(entry, query)}))
        .filter(({s}) => s !== null)
        .sort((a, b) => b.s - a.s || a.entry.name.localeCompare(b.entry.name))
        .map(({entry}) => entry);
}

/** Entries sorted by name, for the "All apps" view. */
export function alphabetical(entries) {
    return [...entries].sort((a, b) => a.name.localeCompare(b.name));
}
