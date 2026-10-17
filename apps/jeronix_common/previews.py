# SPDX-License-Identifier: GPL-3.0-or-later
"""Schematic previews of layouts, drawn from the layout data itself.

The preview is SVG: top bar (JERONIX menu, workspace pills, focused-app
context, clock, status), windows with the layout's title-bar buttons, and
the dock at its position. A dock that hides is drawn translucent with a
dashed outline. Colors come from the design tokens.
"""

W, H = 320, 200
BAR = 14


def _setting(layout, schema_suffix, key, default=None):
    for s in layout.get("settings", []):
        if s["schema"].endswith(schema_suffix) and s["key"] == key:
            return s["value"]
    return default


def layout_preview_svg(layout, tokens, mode="dark"):
    p = tokens["color"][mode]
    b = tokens["brand"]
    show_label = _setting(layout, "jeronix-panel", "show-menu-label", True)
    show_ws = _setting(layout, "jeronix-panel", "show-workspaces", True)
    show_ctx = _setting(layout, "jeronix-panel", "show-window-context", True)
    position = _setting(layout, "jeronix-dock", "position", "bottom")
    behavior = _setting(layout, "jeronix-dock", "behavior", "intellihide")
    buttons = _setting(layout, "wm.preferences", "button-layout", "appmenu:close").split(":")[-1].split(",")
    workspaces = _setting(layout, "wm.preferences", "num-workspaces", 3) or 3
    tiled = not _setting(layout, "mutter", "dynamic-workspaces", True)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           "<defs><linearGradient id='bg' x1='0' y1='0' x2='0.4' y2='1'>"
           f"<stop offset='0' stop-color='{b['graphite']}'/><stop offset='1' stop-color='{b['graphite-deep']}'/>"
           "</linearGradient></defs>",
           f"<rect width='{W}' height='{H}' rx='10' fill='url(#bg)'/>",
           # A hint of the wallpaper's J contours.
           f"<path d='M232 {BAR} V120 A44 44 0 0 1 144 120 V108' fill='none' stroke='{b['copper']}' "
           "stroke-opacity='0.35' stroke-width='2' stroke-linecap='round'/>",
           f"<path d='M10 0 H{W - 10} A10 10 0 0 1 {W} 10 V{BAR} H0 V10 A10 10 0 0 1 10 0 Z' fill='{p['panel']}'/>"]
    # Top bar contents.
    x = 8
    out.append(f"<rect x='{x}' y='4' width='6' height='6' rx='1.5' fill='{p['panel-accent']}'/>")
    x += 10
    if show_label:
        out.append(f"<rect x='{x}' y='5' width='22' height='4' rx='2' fill='{p['on-panel']}' opacity='0.85'/>")
        x += 28
    if show_ws:
        for i in range(min(workspaces, 4)):
            fill = p["panel-accent"] if i == 0 else p["on-panel"]
            out.append(f"<rect x='{x}' y='4' width='8' height='6' rx='3' fill='{fill}' "
                       f"opacity='{1 if i == 0 else 0.5}'/>")
            x += 11
        x += 4
    if show_ctx:
        out.append(f"<rect x='{x}' y='5' width='30' height='4' rx='2' fill='{p['on-panel']}' opacity='0.6'/>")
    out.append(f"<rect x='{W / 2 - 14}' y='5' width='28' height='4' rx='2' fill='{p['on-panel']}' opacity='0.85'/>")
    out.append(f"<rect x='{W - 26}' y='5' width='18' height='4' rx='2' fill='{p['on-panel']}' opacity='0.6'/>")

    # Dock geometry.
    reserve = behavior == "always"
    icons = 5
    if position == "bottom":
        dw, dh = icons * 16 + 12, 22
        dock = (W / 2 - dw / 2, H - dh - 6, dw, dh)
    else:
        dw, dh = 22, icons * 16 + 12
        dx = 6 if position == "left" else W - dw - 6
        dock = (dx, BAR + (H - BAR - dh) / 2, dw, dh)

    # Work area for windows.
    left, top, right, bottom = 10, BAR + 10, W - 10, H - 10
    if reserve:
        if position == "bottom":
            bottom = dock[1] - 6
        elif position == "left":
            left = dock[0] + dock[2] + 6
        else:
            right = dock[0] - 6
    windows = ([(left, top, (right - left) / 2 - 4, bottom - top),
                (left + (right - left) / 2 + 4, top, (right - left) / 2 - 4, bottom - top)] if tiled else
               [(left + 14, top + 6, (right - left) * 0.62, (bottom - top) * 0.66),
                (left + (right - left) * 0.34, top + (bottom - top) * 0.28, (right - left) * 0.6,
                 (bottom - top) * 0.62)])
    for i, (wx, wy, ww, wh) in enumerate(windows):
        out.append(f"<rect x='{wx:.1f}' y='{wy:.1f}' width='{ww:.1f}' height='{wh:.1f}' rx='5' "
                   f"fill='{p['surface-raised']}' stroke='{p['border']}'/>")
        out.append(f"<rect x='{wx:.1f}' y='{wy:.1f}' width='{ww:.1f}' height='10' rx='5' fill='{p['surface-overlay']}'/>")
        bx = wx + ww - 8
        for _ in [b for b in buttons if b]:
            out.append(f"<circle cx='{bx:.1f}' cy='{wy + 5:.1f}' r='2.2' fill='{p['text-muted']}'/>")
            bx -= 7
        lines = 4 if i == 0 else 3
        for n in range(lines):
            out.append(f"<rect x='{wx + 8:.1f}' y='{wy + 18 + n * 9:.1f}' width='{ww * (0.7 - n * 0.1):.1f}' "
                       f"height='3' rx='1.5' fill='{p['text-muted']}' opacity='0.45'/>")

    # Dock on top of windows.
    dx, dy, dw, dh = dock
    hidden = behavior == "autohide"  # appears only at the screen edge
    dash = " stroke-dasharray='3 2'" if hidden else ""
    out.append(f"<rect x='{dx:.1f}' y='{dy:.1f}' width='{dw:.1f}' height='{dh:.1f}' rx='7' "
               f"fill='{p['surface-raised']}' opacity='{0.55 if hidden else 0.96}' stroke='{p['border']}'{dash}/>")
    for i in range(icons):
        if position == "bottom":
            ix, iy = dx + 6 + i * 16, dy + 5
        else:
            ix, iy = dx + 5, dy + 6 + i * 16
        fill = b["copper"] if i == 0 else (b["sage"] if i == 2 else p["text-muted"])
        out.append(f"<rect x='{ix:.1f}' y='{iy:.1f}' width='12' height='12' rx='3' fill='{fill}' "
                   f"opacity='{0.5 if hidden else 0.9}'/>")
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
