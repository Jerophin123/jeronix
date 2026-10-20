#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX symbolic icons: the Settings categories and the Control Center
glyphs, drawn on a 16 px grid from a few filled primitives.

Symbolic icons must be fill-only: GTK and GNOME Shell recolor them by
forcing `fill` on every shape, so strokes would turn into blobs. Rings and
frames are therefore one path with an even-odd hole, and lines are thin
rounded rectangles.

Usage: scripts/jeronix_symbolic.py build   write the SVGs
       scripts/jeronix_symbolic.py check   fail if a committed SVG is stale
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_DIR = ROOT / "apps" / "settings" / "icons"
CONTROL_CENTER_DIR = ROOT / "desktop" / "extensions" / "jeronix-dock" / "icons"
INK = "#2e3436"


def f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


# -- primitives (each returns path data) -----------------------------------------

def rrect(x, y, w, h, r=0.0):
    r = min(r, w / 2, h / 2)
    if r <= 0:
        return f"M{f(x)} {f(y)}h{f(w)}v{f(h)}h{f(-w)}Z"
    return (f"M{f(x + r)} {f(y)}H{f(x + w - r)}A{f(r)} {f(r)} 0 0 1 {f(x + w)} {f(y + r)}"
            f"V{f(y + h - r)}A{f(r)} {f(r)} 0 0 1 {f(x + w - r)} {f(y + h)}"
            f"H{f(x + r)}A{f(r)} {f(r)} 0 0 1 {f(x)} {f(y + h - r)}"
            f"V{f(y + r)}A{f(r)} {f(r)} 0 0 1 {f(x + r)} {f(y)}Z")


def circle(cx, cy, r):
    return (f"M{f(cx - r)} {f(cy)}A{f(r)} {f(r)} 0 1 0 {f(cx + r)} {f(cy)}"
            f"A{f(r)} {f(r)} 0 1 0 {f(cx - r)} {f(cy)}Z")


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def band(cx, cy, r_out, r_in, a0, a1):
    """Annular sector from angle a0 to a1 (degrees, clockwise, 0 = right)."""
    large = 1 if (a1 - a0) % 360 > 180 else 0
    x0, y0 = _pt(cx, cy, r_out, a0)
    x1, y1 = _pt(cx, cy, r_out, a1)
    x2, y2 = _pt(cx, cy, r_in, a1)
    x3, y3 = _pt(cx, cy, r_in, a0)
    return (f"M{f(x0)} {f(y0)}A{f(r_out)} {f(r_out)} 0 {large} 1 {f(x1)} {f(y1)}"
            f"L{f(x2)} {f(y2)}A{f(r_in)} {f(r_in)} 0 {large} 0 {f(x3)} {f(y3)}Z")


def line(x1, y1, x2, y2, w=1.5):
    """A straight line with round caps, as a filled shape."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    nx, ny = -dy / length * w / 2, dx / length * w / 2
    r = w / 2
    return (f"M{f(x1 + nx)} {f(y1 + ny)}L{f(x2 + nx)} {f(y2 + ny)}"
            f"A{f(r)} {f(r)} 0 0 0 {f(x2 - nx)} {f(y2 - ny)}"
            f"L{f(x1 - nx)} {f(y1 - ny)}A{f(r)} {f(r)} 0 0 0 {f(x1 + nx)} {f(y1 + ny)}Z")


def poly(*points):
    head, *rest = points
    return f"M{f(head[0])} {f(head[1])}" + "".join(f"L{f(x)} {f(y)}" for x, y in rest) + "Z"


def ring(cx, cy, r_out, r_in):
    return ("evenodd", circle(cx, cy, r_out) + circle(cx, cy, r_in))


def frame(x, y, w, h, r, t):
    """A rounded rectangle outline of thickness t."""
    return ("evenodd", rrect(x, y, w, h, r) + rrect(x + t, y + t, w - 2 * t, h - 2 * t, max(0, r - t)))


# -- glyphs: lists of path data or (fill-rule, path data) ------------------------------

def wifi():
    c = (8, 13.2)
    return [circle(*c, 1.6)] + [band(*c, ro, ri, 225, 315) for ro, ri in ((5, 3.5), (8, 6.5), (11, 9.5))]


def bluetooth():
    pts = [(4.2, 5), (11.2, 10.8), (8, 13.8), (8, 2.2), (11.2, 5.2), (4.2, 11)]
    return [line(*pts[i], *pts[i + 1], 1.5) for i in range(len(pts) - 1)]


def globe():
    return [ring(8, 8, 6.8, 5.4),
            ("evenodd", "M8 1.2A3.2 6.8 0 1 0 8 14.8A3.2 6.8 0 1 0 8 1.2Z"
                        "M8 2.6A1.8 5.4 0 1 1 8 13.4A1.8 5.4 0 1 1 8 2.6Z"),
            rrect(1.6, 7.3, 12.8, 1.4, 0.7)]


def bell():
    body = "M8 1.6C5.3 1.6 4 3.8 4 6.2V9.6L2.6 11.6V12.2H13.4V11.6L12 9.6V6.2C12 3.8 10.7 1.6 8 1.6Z"
    return [body, circle(8, 13.6, 1.5)]


def sound():
    return [poly((1.5, 6), (4.6, 6), (8.4, 2.4), (8.4, 13.6), (4.6, 10), (1.5, 10)),
            band(8.6, 8, 3.9, 2.5, -50, 50), band(8.6, 8, 6.6, 5.2, -50, 50)]


def appearance():
    return [ring(8, 8, 6.8, 5.4), "M8 2.6A5.4 5.4 0 0 1 8 13.4Z"]


def wallpaper():
    return [frame(1, 2.5, 14, 11, 2, 1.4), poly((3.6, 11.4), (6.8, 7.4), (8.9, 9.9), (10.4, 8.4), (12.4, 11.4)),
            circle(10.6, 5.9, 1.3)]


def control_center():
    return [frame(1, 1.8, 14, 5.6, 2.8, 1.3), circle(3.9, 4.6, 2.2),
            frame(1, 8.6, 14, 5.6, 2.8, 1.3), circle(12.1, 11.4, 2.2)]


def desktop():
    return [frame(1, 1.8, 14, 10, 1.6, 1.4), rrect(2.4, 8.4, 11.2, 2, 0), rrect(6.6, 11.8, 2.8, 1.6, 0),
            rrect(4.4, 13.2, 7.2, 1.4, 0.7)]


def start():
    return [rrect(1.8, 1.8, 5.4, 5.4, 1.4), rrect(8.8, 1.8, 5.4, 5.4, 1.4),
            rrect(1.8, 8.8, 5.4, 5.4, 1.4), rrect(8.8, 8.8, 5.4, 5.4, 1.4)]


def sun():
    rays = [line(*_pt(8, 8, 5.2, a), *_pt(8, 8, 6.9, a), 1.4) for a in range(0, 360, 45)]
    return [circle(8, 8, 3.1)] + rays


def accessibility():
    return [circle(8, 2.6, 1.7), rrect(2, 5, 12, 1.6, 0.8), rrect(7, 5.6, 2, 4.6, 0),
            line(7.6, 9.8, 5.4, 14.4, 1.7), line(8.4, 9.8, 10.6, 14.4, 1.7)]


def multitasking():
    return [frame(1, 1.6, 10, 8, 1.6, 1.3), rrect(5, 6.4, 10, 8, 1.6)]


def battery():
    return [frame(1, 4.4, 12.4, 7.2, 1.8, 1.3), rrect(13.8, 6.5, 1.6, 3, 0.6), rrect(3.2, 6.6, 6, 2.8, 0.5)]


def lock():
    shackle = band(8, 6.6, 3.9, 2.5, 180, 360)
    return [shackle, rrect(4.1, 6.4, 1.4, 1.6, 0), rrect(10.5, 6.4, 1.4, 1.6, 0),
            ("evenodd", rrect(2.8, 7.4, 10.4, 7.4, 1.6) + circle(8, 10.4, 1.15) + rrect(7.45, 10.4, 1.1, 2.4, 0.4))]


def magnifier():
    return [ring(6.6, 6.6, 5.2, 3.8), line(10.4, 10.4, 14.2, 14.2, 2.2)]


def person():
    return [circle(8, 4.8, 3.1), "M2.4 14.6C2.4 11.1 4.9 9.2 8 9.2C11.1 9.2 13.6 11.1 13.6 14.6Z"]


def flag():
    return [rrect(2.6, 1.6, 1.5, 13, 0.75),
            "M4.1 2.4C6.3 1.4 8 3.2 10.2 2.6C11.4 2.3 12.3 2 13.6 1.8V9.4C12.3 9.6 11.4 9.9 10.2 10.2"
            "C8 10.8 6.3 9 4.1 10Z"]


def clock():
    return [ring(8, 8, 6.8, 5.4), rrect(7.3, 3.9, 1.4, 4.8, 0.7), rrect(7.3, 7.3, 4, 1.4, 0.7)]


def keyboard():
    keys = [rrect(x, y, 1.5, 1.5, 0.3) for y in (5.6, 8) for x in (3.1, 5.3, 7.5, 9.7, 11.9)]
    return [frame(0.6, 3.2, 14.8, 9.6, 1.8, 1.3)] + keys + [rrect(5, 10.3, 6, 1.3, 0.4)]


def mouse():
    return [frame(3.8, 1.2, 8.4, 13.6, 4.2, 1.35), rrect(7.3, 3.6, 1.4, 3.2, 0.7)]


def printer():
    return [frame(4.2, 1.2, 7.6, 4.6, 0.8, 1.2),
            ("evenodd", rrect(1, 5, 14, 6.6, 1.6) + rrect(3.8, 8.6, 8.4, 3, 0)),
            frame(4.2, 8.6, 7.6, 6.2, 0.6, 1.2)]


def sharing():
    a, b, c = (12, 3.4), (4, 8), (12, 12.6)
    return [circle(*a, 2.2), circle(*b, 2.2), circle(*c, 2.2), line(*b, *a, 1.4), line(*b, *c, 1.4)]


def star():
    pts = []
    for i in range(10):
        r = 7 if i % 2 == 0 else 2.9
        pts.append(_pt(8, 8.6, r, -90 + i * 36))
    return [poly(*pts)]


def info():
    return [ring(8, 8, 6.8, 5.4), circle(8, 4.9, 1.05), rrect(7.3, 6.9, 1.4, 5, 0.7)]


def crescent(c1, r1, c2, r2):
    """The part of circle 1 outside circle 2: its far arc, then circle 2's
    arc back between the two intersection points."""
    (x1, y1), (x2, y2) = c1, c2
    d = math.hypot(x2 - x1, y2 - y1)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(r1 * r1 - a * a)
    mx, my = x1 + a * (x2 - x1) / d, y1 + a * (y2 - y1) / d
    px, py = mx + h * (y2 - y1) / d, my - h * (x2 - x1) / d
    qx, qy = mx - h * (y2 - y1) / d, my + h * (x2 - x1) / d
    return (f"M{f(px)} {f(py)}A{f(r1)} {f(r1)} 0 1 0 {f(qx)} {f(qy)}"
            f"A{f(r2)} {f(r2)} 0 0 1 {f(px)} {f(py)}Z")


def moon():
    return [crescent((7.6, 8.4), 6.4, (11.4, 4.8), 5)]


def cup():
    return [("evenodd", "M2 5.4H12V9.6C12 12.4 10 14.4 7 14.4C4 14.4 2 12.4 2 9.6Z"),
            frame(10.6, 6.2, 4.4, 4.6, 2.2, 1.3), rrect(4.2, 1.2, 1.3, 3, 0.65), rrect(7.4, 1.2, 1.3, 3, 0.65)]


def bolt():
    return [poly((9.6, 1), (3, 9.2), (7.4, 9.2), (6.2, 15), (13, 6.6), (8.6, 6.6))]


# The Settings sidebar (page id -> glyph) and the Control Center glyphs.
SETTINGS = {
    "wifi": wifi, "bluetooth": bluetooth, "network": globe, "notifications": bell, "sound": sound,
    "appearance": appearance, "wallpaper": wallpaper, "control-center": control_center, "desktop": desktop,
    "start": start, "displays": sun, "accessibility": accessibility, "multitasking": multitasking,
    "power": battery, "privacy": lock, "search": magnifier, "users": person, "region": flag,
    "datetime": clock, "keyboard": keyboard, "mouse": mouse, "printers": printer, "sharing": sharing,
    "default-apps": star, "about": info,
}
CONTROL_CENTER = {"dark-mode": appearance, "focus": moon, "stay-awake": cup, "power-mode": bolt}


def svg(glyph):
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">']
    for shape in glyph():
        rule, data = shape if isinstance(shape, tuple) else ("nonzero", shape)
        out.append(f'  <path fill="{INK}" fill-rule="{rule}" d="{data}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def outputs():
    files = {SETTINGS_DIR / f"jeronix-settings-{name}-symbolic.svg": svg(g) for name, g in SETTINGS.items()}
    files.update({CONTROL_CENTER_DIR / f"jeronix-cc-{name}-symbolic.svg": svg(g) for name, g in CONTROL_CENTER.items()})
    return files


def main(argv):
    command = argv[1] if len(argv) > 1 else "check"
    stale = []
    for path, text in outputs().items():
        if command == "build":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(str(path.relative_to(ROOT)))
    if stale:
        print("stale symbolic icons (run scripts/jeronix_symbolic.py build):\n  " + "\n  ".join(stale))
        return 1
    print(f"{command}: {len(outputs())} symbolic icons {'written' if command == 'build' else 'up to date'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
