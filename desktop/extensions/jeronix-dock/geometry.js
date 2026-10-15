// SPDX-License-Identifier: GPL-3.0-or-later
//
// Dock placement and sizing. No GNOME Shell imports, so it is unit-tested
// with plain gjs (tests/unit/js/test_dock_geometry.js).

// Gap between the floating dock and the screen edge.
export const MARGIN = 12;
// Padding around each icon inside an item (both sides together); matches
// .jeronix-dock-item padding in the dock stylesheet.
export const ITEM_PADDING = 16;
// Dock padding plus the separator, along the dock's long axis.
export const DOCK_CHROME = 32;
const EDGE = 2;

export const POSITIONS = Object.freeze(['bottom', 'left', 'right']);

export class Geometry {
    /**
     * @param {string} position - bottom, left or right
     * @param {{x: number, y: number, width: number, height: number}} monitor
     * @param {number} panelHeight - top bar height on this monitor
     */
    constructor(position, monitor, panelHeight) {
        if (!POSITIONS.includes(position))
            throw new Error(`unknown dock position ${position}`);
        this.position = position;
        this.monitor = monitor;
        this.panelHeight = panelHeight;
    }

    get vertical() {
        return this.position !== 'bottom';
    }

    /** Length available for the dock along its long axis. */
    get available() {
        const m = this.monitor;
        return this.vertical
            ? m.height - this.panelHeight - 2 * MARGIN - DOCK_CHROME
            : m.width - 2 * MARGIN - DOCK_CHROME;
    }

    /**
     * Container rectangle for a dock of the given natural size. The
     * container includes the margin on the screen-edge side, so struts and
     * overlap checks cover the gap too.
     */
    place(dockWidth, dockHeight) {
        const m = this.monitor;
        switch (this.position) {
        case 'bottom':
            return {
                x: Math.round(m.x + (m.width - dockWidth) / 2),
                y: m.y + m.height - dockHeight - MARGIN,
                width: dockWidth,
                height: dockHeight + MARGIN,
            };
        case 'left':
        case 'right': {
            const top = m.y + this.panelHeight;
            const y = Math.round(top + (m.height - this.panelHeight - dockHeight) / 2);
            const x = this.position === 'left' ? m.x : m.x + m.width - dockWidth - MARGIN;
            return {x, y, width: dockWidth + MARGIN, height: dockHeight};
        }
        }
        throw new Error('unreachable');
    }

    /** The thin strip at the screen edge that reveals a hidden dock. */
    edgeStrip(rect) {
        const m = this.monitor;
        switch (this.position) {
        case 'bottom':
            return {x: rect.x, y: m.y + m.height - EDGE, width: rect.width, height: EDGE};
        case 'left':
            return {x: m.x, y: rect.y, width: EDGE, height: rect.height};
        default:
            return {x: m.x + m.width - EDGE, y: rect.y, width: EDGE, height: rect.height};
        }
    }

    /** Translation that moves the dock fully off screen. */
    hiddenOffset(rect) {
        switch (this.position) {
        case 'bottom':
            return {x: 0, y: rect.height};
        case 'left':
            return {x: -rect.width, y: 0};
        default:
            return {x: rect.width, y: 0};
        }
    }
}

/**
 * Picks the largest icon size (in 4 px steps, not below minimum) at which
 * all items fit; if even the minimum does not fit, the items scroll.
 *
 * @returns {{iconSize: number, overflow: boolean, itemsLength: number}}
 *   itemsLength is the length to give the scrolling item area on overflow.
 */
export function fitIconSize({items, extras, preferred, minimum, available}) {
    const step = size => size + ITEM_PADDING;
    const length = size => (items + extras) * step(size);
    let size = Math.max(preferred, minimum);
    while (size > minimum && length(size) > available)
        size = Math.max(minimum, size - 4);
    const overflow = length(size) > available;
    const room = available - extras * step(size);
    const itemsLength = overflow ? Math.max(step(size), Math.floor(room / step(size)) * step(size)) : -1;
    return {iconSize: size, overflow, itemsLength};
}

/** Insertion index for a drop at coord, given the item centers in order. */
export function dropIndex(centers, coord) {
    let i = 0;
    while (i < centers.length && coord > centers[i])
        i++;
    return i;
}
