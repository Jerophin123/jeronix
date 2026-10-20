#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds JERONIX desktop assets from design/tokens/tokens.json.

Everything this produces is derived and goes to an output directory (default
out/, which Git ignores). Source files are never modified.

    scripts/jeronix_design.py build [--out DIR] [--only extensions,wallpapers,icons,branding]
    scripts/jeronix_design.py check            # token and contrast validation only

Outputs:
    extensions/<uuid>/                        every extension, installable, with
                                              generated stylesheets and schemas
    wallpapers/jeronix-{dark,light}.svg       procedural wallpapers (vector)
    wallpapers/jeronix-{mode}-{W}x{H}.png     rendered at common display sizes
    icons/hicolor/...                         app icon theme layout
    branding/...                              boot, login and welcome PNGs
    build-manifest.json                       what was built, from which tokens
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "design" / "tokens" / "tokens.json"
PLATFORM = ROOT / "config" / "platform.json"
ICONS = ROOT / "design" / "icons"
THEME_TEMPLATE = ROOT / "desktop" / "theme" / "gnome-shell" / "jeronix.css.in"
THEME_EXTENSION = ROOT / "desktop" / "extensions" / "jeronix-shell-theme"
THEME_UUID = "jeronix-shell-theme@jeronix"
EXTENSIONS = ROOT / "desktop" / "extensions"
# Design assets bundled into extensions: {extension dir: {target: design/icons file}}.
EXTENSION_ICONS = {
    "jeronix-panel": {"icons/jeronix-symbolic.svg": "jeronix-mark-symbolic.svg"},
    "jeronix-dock": {"icons/jeronix-start.svg": "jeronix-mark.svg"},
}

MODES = ("dark", "light")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
PLACEHOLDER = re.compile(r"@([a-z0-9-]+)@")
PARTS = ("extensions", "wallpapers", "icons", "branding", "desktop")

# Common desktop resolutions the wallpapers are rendered at. The vector
# source adapts its composition to each aspect ratio instead of cropping.
WALLPAPER_SIZES = ((1920, 1080), (2560, 1440), (2560, 1600), (3840, 2160))
# Sizes below this use the small-size master, which has thicker strokes.
SMALL_ICON_MAX = 24


# -- tokens and color ------------------------------------------------------

def load_tokens(path=TOKENS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_platform(path=PLATFORM):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hex_to_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def relative_luminance(value):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(value)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b):
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def blend(fg, bg, alpha):
    """Opaque result of drawing fg at the given alpha over bg."""
    return rgb_to_hex(f * alpha + b * (1 - alpha) for f, b in zip(hex_to_rgb(fg), hex_to_rgb(bg)))


def rgba(value, alpha):
    r, g, b = hex_to_rgb(value)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def palette(tokens, mode):
    """Color roles for one mode, including roles derived from interaction tokens.

    Derived opaque roles are computed here (not with St's st-mix()) so their
    contrast can be tested.
    """
    p = dict(tokens["color"][mode])
    i = tokens["interaction"]
    p["control-hover"] = blend(p["text"], p["surface-overlay"], i["hover-opacity"])
    p["control-pressed"] = blend(p["text"], p["surface-overlay"], i["pressed-opacity"])
    # The lock and login screens sit on a darkened wallpaper in both modes,
    # so their text is white and warnings use the dark-mode warning color.
    p["on-lock"] = "#FFFFFF"
    p["lock-warning"] = tokens["color"]["dark"]["warning"]
    return p


def validate_tokens(tokens):
    """Returns a list of problems; empty means valid."""
    problems = []
    required = ("schema", "name", "version", "brand", "color", "interaction", "contrast",
                "typography", "spacing-px", "component", "radius-px", "elevation",
                "motion", "icon-size-px", "wallpaper")
    problems += [f"missing top-level key {k!r}" for k in required if k not in tokens]
    if problems:
        return problems
    if tokens["schema"] != 2:
        problems.append("schema must be 2")
    if not re.match(r"^\d+\.\d+\.\d+$", tokens["version"]):
        problems.append("version must be semver")
    if set(tokens["color"]) != set(MODES):
        problems.append(f"color modes must be exactly {MODES}")
    elif set(tokens["color"]["dark"]) != set(tokens["color"]["light"]):
        problems.append("dark and light define different roles")
    for scope, colors in [("brand", tokens["brand"])] + [(f"color.{m}", tokens["color"].get(m, {})) for m in MODES]:
        problems += [f"{scope}.{k}: {v!r} is not #RRGGBB" for k, v in colors.items() if not HEX.match(str(v))]
    for key in ("hover-opacity", "pressed-opacity", "selected-opacity", "disabled-opacity"):
        v = tokens["interaction"].get(key)
        if not isinstance(v, (int, float)) or not 0 < v < 1:
            problems.append(f"interaction.{key} must be between 0 and 1")
    for mode, scheme in tokens["wallpaper"].items():
        if mode == "description":
            continue
        problems += [f"wallpaper.{mode}.{k}: unknown brand color {v!r}"
                     for k, v in scheme.items() if v not in tokens["brand"]]
    for name, shadow in tokens["elevation"].items():
        if set(shadow) != {"offset-y-px", "blur-px", "spread-px", "opacity"}:
            problems.append(f"elevation.{name} has wrong fields")
    for group in ("spacing-px", "radius-px"):
        values = list(tokens[group].values())
        if values != sorted(values) or any(not isinstance(v, int) or v < 0 for v in values):
            problems.append(f"{group} must be ascending non-negative integers")
    if any(v % 4 for v in tokens["spacing-px"].values()):
        problems.append("spacing-px must stay on the 4 px grid")
    sizes = tokens["icon-size-px"]
    if sizes != sorted(set(sizes)):
        problems.append("icon-size-px must be ascending and unique")
    durations = list(tokens["motion"]["duration-ms"].values())
    if durations != sorted(durations):
        problems.append("motion durations must be ascending")
    scale = tokens["typography"]["scale"]
    if scale.get("body") != 1.0 or list(scale.values()) != sorted(scale.values()):
        problems.append("typography.scale must be ascending with body = 1.0")
    return problems


def contrast_report(tokens):
    """[(scope, fg, bg, ratio, minimum)] for every declared pair."""
    rows = []
    for mode in MODES:
        p = palette(tokens, mode)
        for fg, bg, minimum in tokens["contrast"]["pairs"]:
            rows.append((mode, fg, bg, contrast_ratio(p[fg], p[bg]), minimum))
    brand = tokens["brand"]
    for fg, bg, minimum in tokens["contrast"]["brand-pairs"]:
        rows.append(("brand", fg, bg, contrast_ratio(brand[fg], brand[bg]), minimum))
    return rows


# -- GNOME Shell theme -----------------------------------------------------

def shadow_css(spec, color="#000000", alpha_scale=1.0):
    return (f"0 {spec['offset-y-px']}px {spec['blur-px']}px {spec['spread-px']}px "
            f"{rgba(color, round(spec['opacity'] * alpha_scale, 3))}")


def theme_variables(tokens, mode, platform):
    p = palette(tokens, mode)
    i = tokens["interaction"]
    v = {"mode": mode,
         "tokens-version": tokens["version"],
         "shell-versions": ", ".join(platform["gnome_shell"]["supported_versions"])}
    v.update(p)
    v["hover"] = rgba(p["text"], i["hover-opacity"])
    v["pressed"] = rgba(p["text"], i["pressed-opacity"])
    v["selected"] = rgba(p["accent"], i["selected-opacity"])
    v["text-disabled"] = rgba(p["text"], i["disabled-opacity"])
    v["panel-hover"] = rgba(p["on-panel"], i["hover-opacity"] * 2)
    v["panel-pressed"] = rgba(p["on-panel"], i["pressed-opacity"] * 2)
    v["selection"] = rgba(p["accent"], i["selected-opacity"] * 1.5)
    v["selected-secondary"] = rgba(p["accent-secondary"], i["selected-opacity"])
    v["dock-surface"] = rgba(p["surface-raised"], 0.86)  # translucent, Mica-like
    v["dock-highlight"] = rgba(p["text"], 0.14)  # light top edge of the bar
    # Light popovers need softer shadows than dark ones to look the same.
    shadow_scale = 1.0 if mode == "dark" else 0.5
    for name, spec in tokens["elevation"].items():
        v[f"shadow-{name}"] = shadow_css(spec, alpha_scale=shadow_scale)
    for name, px in tokens["spacing-px"].items():
        v[f"space-{name}"] = f"{px}px"
    for name, px in tokens["radius-px"].items():
        v[f"radius-{name}"] = f"{px}px"
    for name, factor in tokens["typography"]["scale"].items():
        v[f"font-{name}"] = f"{factor:g}em"
    for name, weight in tokens["typography"]["weight"].items():
        v[f"weight-{name}"] = str(weight)
    for name, ms in tokens["motion"]["duration-ms"].items():
        v[f"duration-{name}"] = f"{ms}ms"
    c = tokens["component"]
    v["border-width"] = f"{c['border-width-px']}px"
    v["focus-width"] = f"{c['focus-ring-width-px']}px"
    v["control-min-height"] = f"{c['control-min-height-px']}px"
    v["popover-min-width"] = f"{c['popover-min-width-em']}em"
    v["search-entry-width"] = f"{c['search-entry-width-em']}em"
    v.update(live_accent(mode, i))
    return v


def live_accent(mode, interaction):
    """The shell's accent-colored parts follow the accent chosen in Settings
    (org.gnome.desktop.interface accent-color) as it changes: St resolves
    -st-accent-color itself. The tokens' accent is what the default, blue,
    is designed and contrast-checked against. Focus rings and the panel's
    light accent keep their token colors, as Windows keeps its focus ring."""
    adjust = "st-lighten" if mode == "dark" else "st-darken"
    return {
        "accent": "-st-accent-color",
        "on-accent": "-st-accent-fg-color",
        "accent-strong": f"{adjust}(-st-accent-color, 5%)",
        "selected": f"st-transparentize(-st-accent-color, {1 - interaction['selected-opacity']:g})",
        "selection": f"st-transparentize(-st-accent-color, {1 - interaction['selected-opacity'] * 1.5:g})",
    }


def render_template(template, variables):
    unknown = sorted(set(PLACEHOLDER.findall(template)) - set(variables))
    if unknown:
        raise ValueError(f"unknown theme placeholders: {', '.join(unknown)}")
    return PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), template)


def render_shell_css(tokens, mode, platform, template=None):
    template = THEME_TEMPLATE.read_text(encoding="utf-8") if template is None else template
    return render_template(template, theme_variables(tokens, mode, platform))


def theme_checks(tokens, mode):
    """Computed-style expectations for the real shell (theme_lifecycle.py).

    Each check builds a chain of St widgets ({name, style, pseudo}) inside the
    shell and compares one resolved property of the innermost one. Checks
    with "follows" expect the shell's live accent ("accent") or the text
    color on it ("accent-fg") instead; "expect" is then the default's token.
    """
    p = palette(tokens, mode)
    return [
        {"what": "top panel background",
         "chain": [{"name": "panel"}], "property": "background-color", "expect": p["panel"]},
        {"what": "panel button text",
         "chain": [{"name": "panel"}, {"style": "panel-button"}], "property": "color", "expect": p["on-panel"]},
        {"what": "popover surface",
         "chain": [{"style": "popup-menu-content"}], "property": "background-color", "expect": p["surface-raised"]},
        {"what": "popover text",
         "chain": [{"style": "popup-menu"}], "property": "color", "expect": p["text"]},
        {"what": "quick toggle (off)",
         "chain": [{"style": "quick-toggle button"}], "property": "background-color", "expect": p["surface-overlay"]},
        {"what": "quick toggle (on)",
         "chain": [{"style": "quick-toggle button", "pseudo": "checked"}], "property": "background-color",
         "expect": p["accent"], "follows": "accent"},
        {"what": "quick toggle (on) text",
         "chain": [{"style": "quick-toggle button", "pseudo": "checked"}], "property": "color",
         "expect": p["on-accent"], "follows": "accent-fg"},
        {"what": "search entry",
         "chain": [{"style": "search-entry"}], "property": "background-color", "expect": p["surface-raised"]},
        {"what": "search results section",
         "chain": [{"style": "search-section-content"}], "property": "background-color",
         "expect": p["surface-raised"]},
        {"what": "notification banner",
         "chain": [{"style": "message"}], "property": "background-color", "expect": p["surface-overlay"]},
        {"what": "switcher / OSD surface",
         "chain": [{"style": "switcher-list"}], "property": "background-color", "expect": p["surface-raised"]},
        {"what": "modal dialog surface",
         "chain": [{"style": "modal-dialog"}], "property": "background-color", "expect": p["surface-raised"]},
        {"what": "keyboard focus ring on overview tiles",
         "chain": [{"style": "overview-tile", "pseudo": "focus"}], "property": "box-shadow",
         "expect": p["focus-ring"]},
        {"what": "keyboard focus ring on quick toggles",
         "chain": [{"style": "quick-toggle button", "pseudo": "focus"}], "property": "box-shadow",
         "expect": p["focus-ring"]},
        # Lock and login screens: white text and light-blue focus in both modes.
        {"what": "lock screen clock",
         "chain": [{"style": "unlock-dialog-clock"}], "property": "color", "expect": p["on-lock"]},
        {"what": "password field focus ring",
         "chain": [{"style": "login-dialog-prompt-entry", "pseudo": "focus"}], "property": "box-shadow",
         "expect": p["panel-accent"]},
    ]


def extension_dirs():
    return sorted(p for p in EXTENSIONS.iterdir() if (p / "metadata.json").is_file())


def stylesheet_template(ext_dir):
    """The token template an extension's stylesheets are generated from."""
    if ext_dir == THEME_EXTENSION:
        return THEME_TEMPLATE
    template = ext_dir / "stylesheet.css.in"
    return template if template.is_file() else None


def build_extension(tokens, platform, ext_dir, out):
    """Copies one extension into out/extensions/<uuid> and adds its derived
    files: stylesheet-{dark,light}.css, gschemas.compiled, bundled icons."""
    uuid = json.loads((ext_dir / "metadata.json").read_text(encoding="utf-8"))["uuid"]
    dest = out / "extensions" / uuid
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ext_dir, dest, ignore=shutil.ignore_patterns("*.in", "gschemas.compiled", "__pycache__"))
    built = []
    template = stylesheet_template(ext_dir)
    if template:
        for mode in MODES:
            css = render_template(template.read_text(encoding="utf-8"), theme_variables(tokens, mode, platform))
            path = dest / f"stylesheet-{mode}.css"
            path.write_text(css, encoding="utf-8")
            built.append(path)
    if list((dest / "schemas").glob("*.gschema.xml")):
        subprocess.run(["glib-compile-schemas", "--strict", str(dest / "schemas")], check=True)
        built.append(dest / "schemas" / "gschemas.compiled")
    for target, source in EXTENSION_ICONS.get(ext_dir.name, {}).items():
        (dest / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICONS / source, dest / target)
        built.append(dest / target)
    return built


def build_extensions(tokens, platform, out):
    built = []
    for ext_dir in extension_dirs():
        built += build_extension(tokens, platform, ext_dir, out)
    return built


# -- wallpapers -------------------------------------------------------------

# Per-mode artistic parameters. Colors come from tokens["wallpaper"].
WALLPAPER_STYLE = {
    "dark": {"line-opacity": (0.34, 0.07), "glow-opacity": 0.14, "seed-opacity": 0.8},
    "light": {"line-opacity": (0.30, 0.06), "glow-opacity": 0.20, "seed-opacity": 0.75},
}


def wallpaper_svg(tokens, mode, width, height):
    """Procedural wallpaper: nested J contours rising off the top edge.

    The innermost contour and its seed echo the logo's proportions, so the
    mark is present without being printed on the desktop.
    """
    scheme = {k: tokens["brand"][v] for k, v in tokens["wallpaper"][mode].items()}
    style = WALLPAPER_STYLE[mode]
    s = height  # composition unit, so the art scales with the screen
    cx, cy = width * 0.62, s * 0.54
    count = 9
    first_op, last_op = style["line-opacity"]

    def f(v):
        return f"{v:.1f}".rstrip("0").rstrip(".")

    lines = []
    for n in range(count):
        r = s * (0.10 + 0.046 * n)
        stem_x = cx + r
        hook = cy - r * 0.26
        op = first_op + (last_op - first_op) * n / (count - 1)
        w = s * (0.011 if n == 0 else 0.0032)
        lines.append(
            f'  <path d="M{f(stem_x)} {f(-s * 0.05)}V{f(cy)}A{f(r)} {f(r)} 0 0 1 {f(cx - r)} {f(cy)}V{f(hook)}" '
            f'fill="none" stroke="{scheme["line"]}" stroke-opacity="{op:.3f}" stroke-width="{f(w)}" '
            f'stroke-linecap="round"/>')
    r0 = s * 0.10
    # Seed placed as in the logo, but sized to the line weight, not the bowl.
    seed_x, seed_y, seed_r = cx - 0.30 * r0, cy - 1.52 * r0, s * 0.013
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- JERONIX {mode} wallpaper, {width}x{height}. Generated by scripts/jeronix_design.py from "
        f"design tokens {tokens['version']}. SPDX-License-Identifier: CC-BY-SA-4.0 -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "  <defs>",
        '    <linearGradient id="base" x1="0" y1="0" x2="0.35" y2="1">',
        f'      <stop offset="0" stop-color="{scheme["base-top"]}"/>',
        f'      <stop offset="1" stop-color="{scheme["base-bottom"]}"/>',
        "    </linearGradient>",
        f'    <radialGradient id="glow" gradientUnits="userSpaceOnUse" cx="{f(cx)}" cy="{f(cy)}" r="{f(s * 0.62)}">',
        f'      <stop offset="0" stop-color="{scheme["line"]}" stop-opacity="{style["glow-opacity"]}"/>',
        f'      <stop offset="1" stop-color="{scheme["line"]}" stop-opacity="0"/>',
        "    </radialGradient>",
        "  </defs>",
        f'  <rect width="{width}" height="{height}" fill="url(#base)"/>',
        f'  <rect width="{width}" height="{height}" fill="url(#glow)"/>',
        *lines,
        f'  <circle cx="{f(seed_x)}" cy="{f(seed_y)}" r="{f(seed_r)}" fill="{scheme["seed"]}" '
        f'fill-opacity="{style["seed-opacity"]}"/>',
        "</svg>",
        "",
    ])


def render_svg(svg, png_path, width, height):
    """Renders SVG text or a file path to a PNG.

    Uses gdk-pixbuf's librsvg loader, which ships with every Ubuntu desktop,
    so no extra packages (Inkscape, rsvg-convert, python3-gi-cairo) are needed.
    """
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, Gio, GLib

    data = Path(svg).read_bytes() if isinstance(svg, Path) else svg.encode("utf-8")
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, width, height, False, None)
    except GLib.Error as e:
        raise RuntimeError(f"librsvg failed to render {png_path.name}: {e.message}") from e
    if (pixbuf.get_width(), pixbuf.get_height()) != (width, height):
        raise RuntimeError(f"{png_path.name}: rendered {pixbuf.get_width()}x{pixbuf.get_height()}, "
                           f"expected {width}x{height}")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(png_path), "png", ["compression"], ["9"])
    return png_path


def build_wallpapers(tokens, out, sizes=WALLPAPER_SIZES):
    dest = out / "wallpapers"
    dest.mkdir(parents=True, exist_ok=True)
    built = []
    for mode in MODES:
        # The reference SVG is 16:9 at 4K; each PNG is composed for its own size.
        svg_path = dest / f"jeronix-{mode}.svg"
        svg_path.write_text(wallpaper_svg(tokens, mode, 3840, 2160), encoding="utf-8")
        built.append(svg_path)
        for w, h in sizes:
            built.append(render_svg(wallpaper_svg(tokens, mode, w, h), dest / f"jeronix-{mode}-{w}x{h}.png", w, h))
    return built


# -- icons and branding ------------------------------------------------------

def build_icons(tokens, out):
    base = out / "icons" / "hicolor"
    built = []
    for size in tokens["icon-size-px"]:
        source = ICONS / ("jeronix-mark-small.svg" if size <= SMALL_ICON_MAX else "jeronix-mark.svg")
        built.append(render_svg(source, base / f"{size}x{size}" / "apps" / "jeronix.png", size, size))
    for name, source in (("scalable/apps/jeronix.svg", "jeronix-mark.svg"),
                         ("symbolic/apps/jeronix-symbolic.svg", "jeronix-mark-symbolic.svg")):
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICONS / source, target)
        built.append(target)
    # The JERONIX icon theme (and the JERONIX app icons in hicolor).
    import jeronix_icons
    built += jeronix_icons.build(tokens, out)
    return built


# (output name, source SVG, width, height). Heights follow each SVG's aspect ratio.
BRANDING = (
    ("jeronix-boot.png", "jeronix-boot.svg", 256, 184),
    ("jeronix-boot@2x.png", "jeronix-boot.svg", 512, 368),
    ("jeronix-login-logo.png", "jeronix-wordmark-on-dark.svg", 242, 56),
    ("jeronix-login-logo@2x.png", "jeronix-wordmark-on-dark.svg", 484, 112),
    ("jeronix-welcome-on-dark.png", "jeronix-lockup-on-dark.svg", 848, 256),
    ("jeronix-welcome-on-light.png", "jeronix-lockup-on-light.svg", 848, 256),
)


# -- every application: GTK 4 / libadwaita colors -------------------------------

# libadwaita's named colors (CSS variables) -> palette roles. Kept in step with
# apps/jeronix_common/style.py (tests/unit/test_theme.py compares them). The
# accent is not among them: libadwaita follows the accent chosen in Settings
# live, and a fixed one here would override that choice in every app.
GTK_COLORS = {
    "window-bg-color": "surface", "window-fg-color": "text",
    "view-bg-color": "surface-raised", "view-fg-color": "text",
    "headerbar-bg-color": "surface", "headerbar-fg-color": "text", "headerbar-backdrop-color": "surface",
    "sidebar-bg-color": "surface-overlay", "sidebar-fg-color": "text", "sidebar-backdrop-color": "surface-overlay",
    "secondary-sidebar-bg-color": "surface-raised", "secondary-sidebar-fg-color": "text",
    "card-bg-color": "surface-raised", "card-fg-color": "text",
    "popover-bg-color": "surface-raised", "popover-fg-color": "text",
    "dialog-bg-color": "surface-raised", "dialog-fg-color": "text",
    "thumbnail-bg-color": "surface-raised", "thumbnail-fg-color": "text",
    "success-color": "success", "warning-color": "warning", "error-color": "danger",
}


def gtk4_css(tokens):
    """The JERONIX colors for every GTK 4 / libadwaita application, light
    and dark. Not applied in high contrast, which keeps its own colors."""
    def block(mode):
        p = palette(tokens, mode)
        return "\n".join(f"  --{name}: {p[role]};" for name, role in GTK_COLORS.items())
    return ("/* JERONIX colors for GTK 4 / libadwaita applications. Generated by\n"
            " * scripts/jeronix_design.py from design/tokens/tokens.json; imported from\n"
            " * ~/.config/gtk-4.0/gtk.css by the JERONIX user setup. */\n"
            "@media (prefers-contrast: no-preference) {\n:root {\n" + block("light") + "\n}\n}\n\n"
            "@media (prefers-color-scheme: dark) and (prefers-contrast: no-preference) {\n:root {\n"
            + block("dark") + "\n}\n}\n")


# -- the terminal (Ptyxis) -------------------------------------------------------------

# ANSI colors 0-15 per mode, chosen for contrast on the JERONIX terminal
# backgrounds (tests/unit/test_theme.py checks the colored ones).
TERMINAL_ANSI = {
    "dark": ["#2A3140", "#F08A80", "#93C49E", "#E8C27A", "#4CC2FF", "#C9A0F0", "#6FD6D6", "#C2CCDA",
             "#6F7B8E", "#F7A59C", "#B5DDBC", "#F2D49A", "#99DFFF", "#DCC0F7", "#9FE6E6", "#FFFFFF"],
    "light": ["#1A2130", "#A8261E", "#2E6B3F", "#7A5600", "#005FB8", "#7A3E9D", "#0F6670", "#536073",
              "#66738A", "#B83228", "#2F7A47", "#865F00", "#0067C7", "#8746AD", "#11707A", "#2F3949"],
}
TERMINAL_BACKGROUND = {"dark": "surface", "light": "surface-raised"}
# The colored ANSI entries (red..cyan, normal and bright).
TERMINAL_COLORED = (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14)


def ptyxis_palette(tokens):
    """A Ptyxis palette file (GKeyFile) named JERONIX."""
    lines = ["[Palette]", "Name=JERONIX", ""]
    for mode, section in (("light", "Light"), ("dark", "Dark")):
        p = palette(tokens, mode)
        lines += [f"[{section}]", f"Background={p[TERMINAL_BACKGROUND[mode]]}", f"Foreground={p['text']}",
                  f"Cursor={p['accent']}"]
        lines += [f"Color{i}={color}" for i, color in enumerate(TERMINAL_ANSI[mode])] + [""]
    return "\n".join(lines)


def build_desktop(tokens, out):
    """Files for every app and the terminal: GTK colors, the Ptyxis palette."""
    dest = out / "desktop"
    dest.mkdir(parents=True, exist_ok=True)
    gtk = dest / "gtk-4.0.css"
    gtk.write_text(gtk4_css(tokens), encoding="utf-8")
    pal = dest / "JERONIX.palette"
    pal.write_text(ptyxis_palette(tokens), encoding="utf-8")
    return [gtk, pal]


def build_branding(out):
    return [render_svg(ICONS / src, out / "branding" / name, w, h) for name, src, w, h in BRANDING]


def build(out, parts=PARTS):
    tokens, platform = load_tokens(), load_platform()
    problems = validate_tokens(tokens)
    failing = [r for r in contrast_report(tokens) if r[3] < r[4]]
    if problems or failing:
        raise SystemExit("token validation failed:\n  " + "\n  ".join(
            problems + [f"{m}: {fg} on {bg} {ratio:.2f} < {mn}" for m, fg, bg, ratio, mn in failing]))
    out.mkdir(parents=True, exist_ok=True)
    built = []
    if "extensions" in parts:
        built += build_extensions(tokens, platform, out)
    if "wallpapers" in parts:
        built += build_wallpapers(tokens, out)
    if "icons" in parts:
        built += build_icons(tokens, out)
    if "branding" in parts:
        built += build_branding(out)
    if "desktop" in parts:
        built += build_desktop(tokens, out)
    manifest = {"tokens-version": tokens["version"], "parts": list(parts),
                "files": sorted(str(p.relative_to(out)) for p in built)}
    (out / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return built


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build derived assets")
    b.add_argument("--out", type=Path, default=ROOT / "out")
    b.add_argument("--only", default=",".join(PARTS), help=f"comma-separated subset of {','.join(PARTS)}")
    sub.add_parser("check", help="validate tokens and contrast")
    args = ap.parse_args(argv)

    if args.cmd == "check":
        tokens = load_tokens()
        problems = validate_tokens(tokens)
        for p in problems:
            print(f"FAIL {p}")
        for scope, fg, bg, ratio, minimum in contrast_report(tokens):
            ok = ratio >= minimum
            problems += [] if ok else [fg]
            print(f"{'ok  ' if ok else 'FAIL'} {scope:5} {fg:>14} on {bg:<16} {ratio:5.2f}:1 (min {minimum})")
        return 1 if problems else 0

    parts = tuple(p for p in args.only.split(",") if p)
    unknown = set(parts) - set(PARTS)
    if unknown:
        ap.error(f"unknown parts: {', '.join(sorted(unknown))}")
    built = build(args.out.resolve(), parts)
    print(f"built {len(built)} files in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
