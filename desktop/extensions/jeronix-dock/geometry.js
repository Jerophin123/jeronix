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

    /**
     * Full-width Windows 11-style taskbar along the bottom edge (no margin;
     * the bar itself is the edge).
     */
    placeTaskbar(height) {
        if (this.position !== 'bottom')
            throw new Error('the full-width taskbar only sits at the bottom');
        const m = this.monitor;
        return {x: m.x, y: m.y + m.height - height, width: m.width, height};
    }

    /** Length left for app icons in a taskbar whose tray is trayWidth wide.
     *  The app group is centered, so the tray's width is kept free on both
     *  sides. */
    taskbarAvailable(trayWidth) {
        return this.monitor.width - 2 * trayWidth - 2 * MARGIN - DOCK_CHROME;
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
// Gap kept between the app group and the tray when the group is pushed left.
export const TRAY_GAP = 8;

/**
 * Horizontal layout of the taskbar row (offsets within the bar's content
 * box). The tray sits at the right end. The app group is centered on the
 * whole bar (not on the space left of the tray), like Windows 11, unless
 * that would run into the tray: then it moves left just enough.
 *
 * The live updates area (liveWidth, 0 for none) takes the place Windows
 * gives its widgets: the left end of the bar. A centered group stays
 * centered (the area uses the free space beside it); a left-aligned group
 * follows the area, as the icons follow the widgets in Windows 11. Where the
 * area does not fit whole it is not shown (liveX is null), and the apps are
 * placed as without it.
 */
export function taskbarRow({width, groupWidth, trayWidth, centered, liveWidth = 0}) {
    const trayX = Math.max(0, width - trayWidth);
    const limit = trayWidth > 0 ? trayX - TRAY_GAP : width;
    let groupX = centered ? Math.round((width - groupWidth) / 2) : 0;
    groupX = Math.max(0, Math.min(groupX, limit - groupWidth));
    groupWidth = Math.max(0, Math.min(groupWidth, limit - groupX));
    let liveX = null;
    if (liveWidth > 0) {
        if (centered && groupX - TRAY_GAP >= liveWidth) {
            liveX = 0;
        } else if (!centered && liveWidth + TRAY_GAP + groupWidth <= limit) {
            liveX = 0;
            groupX = liveWidth + TRAY_GAP;
        }
    }
    return {groupX, groupWidth, trayX, liveX};
}

/**
 * A taskbar module grown toward the panel that opens from it, as [x, width]
 * (offsets in the bar). rects holds each module's resting [x, width]
 * (left may be null); width is the bar's. A module grows from its outer
 * side: the left one to the right, the right one to the left, the center
 * one both ways (equally where it can, else into whichever side has room).
 * It grows up to wanted, never past a neighbour (keeping gap), and never
 * shrinks below its resting width.
 */
export function moduleSpan(rects, side, wanted, gap, width) {
    const [x, w] = rects[side];
    const right = r => r[0] + r[1];
    if (side === 'left') {
        const limit = rects.center ? rects.center[0] - gap : width;
        return [x, Math.max(w, Math.min(wanted, limit - x))];
    }
    if (side === 'right') {
        const limit = rects.center ? right(rects.center) + gap : 0;
        const grown = Math.max(w, Math.min(wanted, right(rects.right) - limit));
        return [right(rects.right) - grown, grown];
    }
    const roomLeft = x - (rects.left ? right(rects.left) + gap : 0);
    const roomRight = (rects.right ? rects.right[0] - gap : width) - right(rects.center);
    const total = Math.max(0, wanted - w);
    let growLeft = Math.max(0, Math.min(roomLeft, total / 2));
    const growRight = Math.max(0, Math.min(roomRight, total - growLeft));
    growLeft = Math.max(0, Math.min(roomLeft, total - growRight));
    return [x - growLeft, w + growLeft + growRight];
}

export function dropIndex(centers, coord) {
    let i = 0;
    while (i < centers.length && coord > centers[i])
        i++;
    return i;
}
