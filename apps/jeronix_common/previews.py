# SPDX-License-Identifier: GPL-3.0-or-later
"""Schematic previews of layouts, drawn from the layout data itself.

The preview is SVG, in the shapes of today's JERONIX shell (the
jeronix-dock extension):

* modules: three floating modules along the bottom (live updates on the
  left, Start, search, Task View and apps in the center, the tray with the
  clock on the right);
* taskbar: one full-width bar along the bottom, its apps centered or at the
  start, the live updates in the free space and the tray at the end;
* floating: a dock along an edge, with GNOME's top bar above.

GNOME's top bar is drawn only when the layout keeps it (the bar carries
the tray and hides it otherwise). Windows carry the layout's title-bar
buttons. A bar that hides until the pointer reaches the edge (autohide) is
drawn translucent with a dashed outline. Colors come from the design
tokens.
"""

W, H = 320, 200
BAR = 14  # GNOME's top bar
ICON = 11  # an app icon on a bar


def _setting(layout, schema_suffix, key, default=None):
    for s in layout.get("settings", []):
        if s["schema"].endswith(schema_suffix) and s["key"] == key:
            return s["value"]
    return default


def shape(layout):
    """What the preview draws, from the layout's settings (with the
    extensions' defaults for keys it leaves alone)."""
    dock = lambda key, default: _setting(layout, "jeronix-dock", key, default)  # noqa: E731
    position = dock("position", "bottom")
    style = dock("style", "modules") if position == "bottom" else "floating"
    tray = bool(dock("system-tray", True)) and position == "bottom" and style != "floating"
    return {
        "position": position, "style": style, "behavior": dock("behavior", "intellihide"),
        "alignment": dock("alignment", "center"), "tray": tray,
        "top_bar": not (tray and dock("hide-top-bar", True)),
        "live": bool(dock("live-updates", True)) and style in ("modules", "taskbar"),
        "start": bool(dock("show-start-button", True)), "search": bool(dock("show-search-button", True)),
        "task_view": bool(dock("show-task-view-button", True)) and style != "floating",
        "menu_label": _setting(layout, "jeronix-panel", "show-menu-label", True),
        "workspaces_shown": _setting(layout, "jeronix-panel", "show-workspaces", True),
        "context": _setting(layout, "jeronix-panel", "show-window-context", True),
        "buttons": [b for b in _setting(layout, "wm.preferences", "button-layout", "appmenu:close")
                    .split(":")[-1].split(",") if b],
        "workspaces": _setting(layout, "wm.preferences", "num-workspaces", 3) or 3,
        "fixed_workspaces": not _setting(layout, "mutter", "dynamic-workspaces", True),
    }


def layout_preview_svg(layout, tokens, mode="dark"):
    p = tokens["color"][mode]
    b = tokens["brand"]
    s = shape(layout)
    hidden = s["behavior"] == "autohide"  # appears only at the screen edge
    bar_opacity = 0.55 if hidden else 0.96
    dash = " stroke-dasharray='3 2'" if hidden else ""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           "<defs><linearGradient id='bg' x1='0' y1='0' x2='0.4' y2='1'>"
           f"<stop offset='0' stop-color='{b['graphite']}'/><stop offset='1' stop-color='{b['graphite-deep']}'/>"
           "</linearGradient></defs>",
           f"<rect width='{W}' height='{H}' rx='10' fill='url(#bg)'/>",
           # A hint of the wallpaper's J contours.
           f"<path d='M232 0 V120 A44 44 0 0 1 144 120 V108' fill='none' stroke='{b['blue']}' "
           "stroke-opacity='0.35' stroke-width='2' stroke-linecap='round'/>"]

    def surface(x, y, w, h, r):
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' rx='{r}' "
                   f"fill='{p['surface-raised']}' opacity='{bar_opacity}' stroke='{p['border']}'{dash}/>")

    def line(x, y, w, opacity=0.85, color=None, h=3):
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h}' rx='{h / 2:g}' "
                   f"fill='{color or p['text']}' opacity='{opacity}'/>")

    def app(x, y, i):
        fill = b["blue"] if i == 0 else (b["sage"] if i == 2 else p["text-muted"])
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{ICON}' height='{ICON}' rx='3' fill='{fill}' "
                   f"opacity='{0.5 if hidden else 0.9}'/>")

    def start(x, y):
        """The JERONIX Start button: the J on its tile."""
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{ICON}' height='{ICON}' rx='3' fill='{p['surface-overlay']}'/>")
        out.append(f"<path d='M{x + 7:.1f} {y + 2.5:.1f} V{y + 6.5:.1f} A2.5 2.5 0 0 1 {x + 2:.1f} {y + 6.5:.1f}' "
                   f"fill='none' stroke='{b['blue']}' stroke-width='1.6' stroke-linecap='round'/>")

    def group(x, y):
        """Start, search, Task View and the apps, from x; returns the end."""
        if s["start"]:
            start(x, y)
            x += ICON + 5
        if s["search"]:
            out.append(f"<rect x='{x:.1f}' y='{y + 1:.1f}' width='26' height='{ICON - 2}' rx='{(ICON - 2) / 2:g}' "
                       f"fill='{p['surface-overlay']}' stroke='{p['border']}' stroke-width='0.6'/>")
            out.append(f"<circle cx='{x + 5.5:.1f}' cy='{y + ICON / 2:.1f}' r='2' fill='none' "
                       f"stroke='{p['text-muted']}' stroke-width='1'/>")
            x += 31
        if s["task_view"]:
            for dx, dy in ((0, 0), (5, 0), (0, 5), (5, 5)):
                out.append(f"<rect x='{x + 1 + dx:.1f}' y='{y + 1 + dy:.1f}' width='4' height='4' rx='1' "
                           f"fill='{p['text']}' opacity='0.8'/>")
            x += ICON + 5
        for i in range(4):
            app(x, y, i)
            x += ICON + 5
        return x - 5

    def group_width():
        return ((ICON + 5) if s["start"] else 0) + (31 if s["search"] else 0) + \
            ((ICON + 5) if s["task_view"] else 0) + 4 * (ICON + 5) - 5

    def live(x, y, w):
        """Live updates: an icon (album art) and two lines."""
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{ICON}' height='{ICON}' rx='3' fill='{b['sage']}' "
                   "opacity='0.9'/>")
        line(x + ICON + 4, y + 1.5, w - ICON - 4)
        line(x + ICON + 4, y + 6.5, (w - ICON - 4) * 0.6, 0.5)

    def tray(x, y):
        """Status icons and the clock; returns its width."""
        for i in range(3):
            out.append(f"<circle cx='{x + 2.5 + i * 6:.1f}' cy='{y + ICON / 2:.1f}' r='2' fill='{p['text']}' "
                       "opacity='0.8'/>")
        line(x + 20, y + 1.5, 22)
        line(x + 24, y + 6.5, 18, 0.5)
        return 42

    # -- the bars --------------------------------------------------------------
    work = [10, 10, W - 10, H - 10]  # left, top, right, bottom of the windows' area
    bars = []  # drawn above the windows
    if s["top_bar"]:
        work[1] = BAR + 10
    if s["position"] == "bottom" and s["style"] == "modules":
        mh, gap, y = 22, 6, H - 22 - 6
        iy = y + (mh - ICON) / 2
        gw = group_width() + 16
        gx = (W - gw) / 2
        bars.append(lambda: (surface(gx, y, gw, mh, 8), group(gx + 8, iy)))
        if s["live"]:
            lw = min(78, gx - gap - 6)
            bars.append(lambda: (surface(6, y, lw, mh, 8), live(6 + 7, iy, lw - 14)))
        if s["tray"]:
            tw = 42 + 16
            bars.append(lambda: (surface(W - 6 - tw, y, tw, mh, 8), tray(W - 6 - tw + 8, iy)))
        if s["behavior"] == "always":
            work[3] = y - 6
    elif s["position"] == "bottom" and s["style"] == "taskbar":
        th = 22
        y, iy = H - th, H - th + (th - ICON) / 2
        gw = group_width()
        gx = (W - gw) / 2 if s["alignment"] == "center" else 10

        def taskbar():
            out.append(f"<path d='M0 {y} H{W} V{H - 10} A10 10 0 0 1 {W - 10} {H} H10 A10 10 0 0 1 0 {H - 10} Z' "
                       f"fill='{p['surface-raised']}' opacity='{bar_opacity}'/>")
            out.append(f"<rect x='0' y='{y}' width='{W}' height='0.8' fill='{p['border']}'/>")
            end = group(gx, iy)
            if s["live"]:
                # In the free space: before a centered group, else after it.
                lx = 10 if s["alignment"] == "center" else end + 12
                live(lx, iy, 64)
            if s["tray"]:
                tray(W - 10 - 42, iy)
        bars.append(taskbar)
        if s["behavior"] == "always":
            work[3] = y - 6
    else:
        # A floating dock along an edge: Start and the apps.
        dock_icons = 5
        length = dock_icons * (ICON + 5) + 9
        if s["position"] == "bottom":
            dx, dy, dw, dh = (W - length) / 2, H - 22 - 6, length, 22
        else:
            top = BAR if s["top_bar"] else 0
            dw, dh = 22, length
            dx = 6 if s["position"] == "left" else W - dw - 6
            dy = top + (H - top - dh) / 2

        def dock():
            surface(dx, dy, dw, dh, 7)
            for i in range(dock_icons):
                x, y = (dx + 7 + i * (ICON + 5), dy + (dh - ICON) / 2) if s["position"] == "bottom" else \
                    (dx + (dw - ICON) / 2, dy + 7 + i * (ICON + 5))
                if i == 0 and s["start"]:
                    start(x, y)
                else:
                    app(x, y, i)
        bars.append(dock)
        if s["behavior"] == "always":
            if s["position"] == "bottom":
                work[3] = dy - 6
            elif s["position"] == "left":
                work[0] = dx + dw + 6
            else:
                work[2] = dx - 6

    # -- the windows -------------------------------------------------------------
    left, top, right, bottom = work
    windows = ([(left, top, (right - left) / 2 - 4, bottom - top),
                (left + (right - left) / 2 + 4, top, (right - left) / 2 - 4, bottom - top)]
               if s["fixed_workspaces"] else
               [(left + 14, top + 6, (right - left) * 0.62, (bottom - top) * 0.66),
                (left + (right - left) * 0.34, top + (bottom - top) * 0.28, (right - left) * 0.6,
                 (bottom - top) * 0.62)])
    for i, (wx, wy, ww, wh) in enumerate(windows):
        out.append(f"<rect x='{wx:.1f}' y='{wy:.1f}' width='{ww:.1f}' height='{wh:.1f}' rx='5' "
                   f"fill='{p['surface']}' stroke='{p['border']}'/>")
        out.append(f"<rect x='{wx:.1f}' y='{wy:.1f}' width='{ww:.1f}' height='10' rx='5' fill='{p['surface-overlay']}'/>")
        bx = wx + ww - 8
        for _ in s["buttons"]:
            out.append(f"<circle cx='{bx:.1f}' cy='{wy + 5:.1f}' r='2.2' fill='{p['text-muted']}'/>")
            bx -= 7
        for row in range(4 if i == 0 else 3):
            line(wx + 8, wy + 18 + row * 9, ww * (0.7 - row * 0.1), 0.45, p["text-muted"])

    # -- GNOME's top bar, when the layout keeps it ----------------------------------------
    if s["top_bar"]:
        out.append(f"<path d='M10 0 H{W - 10} A10 10 0 0 1 {W} 10 V{BAR} H0 V10 A10 10 0 0 1 10 0 Z' "
                   f"fill='{p['panel']}'/>")
        x = 8
        out.append(f"<rect x='{x}' y='4' width='6' height='6' rx='1.5' fill='{p['panel-accent']}'/>")
        x += 10
        if s["menu_label"]:
            line(x, 5, 22, 0.85, p["on-panel"], 4)
            x += 28
        if s["workspaces_shown"]:
            for i in range(min(s["workspaces"], 4)):
                out.append(f"<rect x='{x}' y='4' width='8' height='6' rx='3' "
                           f"fill='{p['panel-accent'] if i == 0 else p['on-panel']}' opacity='{1 if i == 0 else 0.5}'/>")
                x += 11
            x += 4
        if s["context"]:
            line(x, 5, 30, 0.6, p["on-panel"], 4)
        if not s["tray"]:  # the clock and status stay up here
            line(W / 2 - 14, 5, 28, 0.85, p["on-panel"], 4)
            line(W - 26, 5, 18, 0.6, p["on-panel"], 4)

    for draw in bars:
        draw()
    out.append("</svg>")
    return "\n".join(out)


def preview_texture(layout, tokens, mode="dark", scale=2):
    """A Gdk.Texture of the preview, rendered by gdk-pixbuf's SVG loader at
    `scale` times the nominal size for sharp HiDPI display."""
    import gi
    gi.require_version("Gdk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib
    data = layout_preview_svg(layout, tokens, mode).encode("utf-8")
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
    pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, W * scale, H * scale, True, None)
    return Gdk.Texture.new_for_pixbuf(pixbuf)
