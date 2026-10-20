#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX branding for Ubuntu's installer (the ubuntu-desktop-bootstrap snap).

The installer is Canonical's signed snap and stays untouched. It is built to
be branded by distributions on Ubuntu: being a classic snap, it reads
/usr/share/desktop-provision/ from the system (see
github.com/canonical/ubuntu-desktop-provision, "Customization"):

* whitelabel.yaml: the window title, the accent colors, and the picture of
  each page (merged over the installer's own defaults);
* images/: those pictures, by name (`image` and `image-dark`);
* slides/<n>/slide_<locale>.html: the slideshow shown while installing,
  in order, with slide_en_US.html as the fallback for every language.

The product name in the installer's texts ("Install JERONIX") comes from the
first line of the ISO's /.disk/info, which build/iso/jeronix_iso.py writes.

Everything here is drawn from the design tokens: the JERONIX logo and J,
illustrations made of a Fluent UI System Icons glyph (MIT, vendored in
design/icons/fluent/illustrations) on a JERONIX card, and slide pictures
from the same schematic desktop as Layout Studio (apps/jeronix_common/
previews.py).

    packaging/jeronix_installer.py OUTDIR    # writes OUTDIR/{whitelabel.yaml,images,slides}
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "scripts"))

PROVISION_DIR = "usr/share/desktop-provision"
ICONS = ROOT / "design" / "icons"
GLYPHS = ICONS / "fluent" / "illustrations"
SIZE = 280  # the installer's page pictures are 280 x 280

# Installer page -> what its picture shows: a glyph (design/icons/fluent/
# illustrations), "hero" (the J), or "logo" (the JERONIX lockup). Page names
# as in the installer's own whitelabel.yml.
PAGES = {
    "locale": "logo",
    "accessibility": "accessibility",
    "try-or-install": "hero",
    "rst": "warning",
    "keyboard": "keyboard",
    "network": "wifi_1",
    "refresh": "arrow_sync",
    "autoinstall": "document_bullet_list",
    "autoinstall-direct": "hard_drive",
    "autoinstall-landscape-domain": "globe",
    "autoinstall-landscape-error": "warning",
    "source-selection": "apps",
    "codecs-and-drivers": "options",
    "not-enough-disk-space": "storage",
    "secure-boot": "shield_checkmark",
    "bitlocker": "lock_closed",
    "storage": "hard_drive",
    "guided-capabilities": "shield_lock",
    "tpm-action": "shield_lock",
    "guided-resize": "hard_drive",
    "guided-reformat": "hard_drive",
    "passphrase-type": "key",
    "passphrase": "key",
    "recovery-key": "key",
    "confirm": "document_bullet_list",
    "identity": "person",
    "active-directory": "people",
    "telemetry": "data_bar_vertical",
    "done": "hero",
    "storage-icon": "mark",
    "error": "warning",
}


def tokens():
    import jeronix_design
    return jeronix_design.load_tokens()


def palette(t, mode):
    b, c = t["brand"], t["color"][mode]
    if mode == "dark":
        return {"halo": b["blue-light"], "halo-opacity": 0.14, "card": c["surface-raised"], "edge": c["border"],
                "glyph": b["blue-light"], "dot": b["sage"], "shadow": "#000000", "shadow-opacity": 0.35}
    return {"halo": b["blue"], "halo-opacity": 0.10, "card": "#FFFFFF", "edge": c["border"],
            "glyph": b["blue"], "dot": b["sage"], "shadow": b["graphite"], "shadow-opacity": 0.10}


def svg_inner(path):
    """An SVG file's drawing (its elements, without the root, title and
    description), and its viewBox size."""
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"<\?xml[^>]*\?>|<!--.*?-->", "", text, flags=re.S)
    m = re.search(r"<svg\b[^>]*viewBox=\"0 0 ([\d.]+) ([\d.]+)\"[^>]*>(.*)</svg>", text, re.S)
    if not m:
        raise ValueError(f"{path}: no viewBox")
    inner = re.sub(r"<title>.*?</title>|<desc>.*?</desc>", "", m.group(3), flags=re.S)
    return inner.strip(), float(m.group(1)), float(m.group(2))


def glyph(name, x, y, size, color):
    """A Fluent glyph, size px square at (x, y), in color."""
    inner, w, _ = svg_inner(GLYPHS / f"{name}.svg")
    inner = inner.replace("<path ", f'<path fill="{color}" ')
    return f'<g transform="translate({x:g} {y:g}) scale({size / w:g})">{inner}</g>'


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n{body}\n</svg>\n')


def illustration(name, t, mode):
    """A page picture: the glyph on a JERONIX card, in a soft halo."""
    p = palette(t, mode)
    c = SIZE / 2
    body = (f'<circle cx="{c}" cy="{c}" r="118" fill="{p["halo"]}" fill-opacity="{p["halo-opacity"]}"/>'
            f'<circle cx="{c}" cy="{c}" r="96" fill="{p["halo"]}" fill-opacity="{p["halo-opacity"]}"/>'
            f'<rect x="69" y="75" width="142" height="142" rx="36" fill="{p["shadow"]}" '
            f'fill-opacity="{p["shadow-opacity"]}"/>'
            f'<rect x="69" y="67" width="142" height="142" rx="36" fill="{p["card"]}" stroke="{p["edge"]}" '
            f'stroke-width="1.5"/>'
            + glyph(name, c - 44, 138 - 44, 88, p["glyph"]) +
            f'<circle cx="203" cy="75" r="11" fill="{p["dot"]}"/>')
    return svg(SIZE, SIZE, body)


def hero(t, mode, size=900):
    """The J on its tile, in the wallpaper's contours: the installer's
    'mascot' (try or install, refresh, done, the first slide)."""
    b = t["brand"]
    inner, w, _ = svg_inner(ICONS / "jeronix-mark.svg")
    c = size / 2
    rings = "".join(f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{b["blue"]}" '
                    f'stroke-opacity="{o}" stroke-width="{size / 180:g}"/>'
                    for r, o in ((size * 0.47, 0.18), (size * 0.40, 0.28), (size * 0.33, 0.40)))
    halo = f'<circle cx="{c}" cy="{c}" r="{size * 0.27:g}" fill="{b["blue"]}" fill-opacity="{0.16 if mode == "dark" else 0.10}"/>'
    mark = size * 0.36
    return svg(size, size, rings + halo +
               f'<g transform="translate({c - mark / 2:g} {c - mark / 2:g}) scale({mark / w:g})">{inner}</g>')


def mark_icon():
    inner, w, _ = svg_inner(ICONS / "jeronix-mark.svg")
    return svg(64, 64, f'<g transform="scale({64 / w:g})">{inner}</g>')


# -- slides -----------------------------------------------------------------------------

SLIDES = [
    ("Welcome to {{ DISTRO }}",
     ["A calm, modern desktop on Ubuntu's long-term support foundation.",
      "While {{ DISTRO }} installs, here is a short tour of what is waiting for you."],
     "hero"),
    ("Start, your way",
     ["Press the Super key, or click the J, to open Start: your pinned apps, recommendations and power, "
      "with search that finds apps, files and settings as you type.",
      "Right-click any app to pin it. Your taskbar sits along the bottom with your apps in the middle."],
     "start"),
    ("Everything at a glance",
     ["The left of the taskbar shows what is going on: the song that is playing, a timer counting down, "
      "a download finishing.",
      "Click it for the widgets: calendar, weather, music and your system at a glance."],
     "widgets"),
    ("Control Center",
     ["Wi-Fi, Bluetooth, sound, brightness, Dark Mode, Focus and more, one click away on the right of the "
      "taskbar, or with Super+S.",
      "Notifications and your calendar sit right beside it."],
     "control"),
    ("A layout that fits",
     ["Pure floats three modules along the bottom. Classic is a familiar full-width taskbar. Studio puts "
      "numbered workspaces first, with a dock that appears on demand.",
      "Switch any time in Layout Studio: your settings are saved first, so you can always go back."],
     "layouts"),
    ("Built on Ubuntu",
     ["{{ DISTRO }} is Ubuntu underneath: the same security updates, drivers and hardware support, and "
      "every app in App Center.",
      "Your files and settings stay yours. {{ DISTRO }} collects nothing about you."],
     "foundation"),
]

SLIDE_STYLE = """body {
  height: 600px;
}

table {
  padding: 8% 60px;
  height: 600px;
}

p {
  margin-bottom: 12px;
}

.h1 {
  font-size: 38px;
}

.hero {
  height: 360px;
  width: 360px;
}

.wide {
  height: 330px;
  width: 528px;
}

.text {
  padding: 0 40px;
}"""


def slide_html(title, paragraphs, image, hero_slide):
    text = "\n".join(f"          <p>{p}</p>" for p in paragraphs)
    picture = f'          <img class="{"hero" if hero_slide else "wide"}" src="{image}" />'
    words = (f'        <td class="text">\n          <p class="h1">{title}</p>\n{text}\n        </td>')
    cells = f"{words}\n        <td>\n{picture}\n        </td>" if hero_slide else \
        f"        <td>\n{picture}\n        </td>\n{words}"
    return (f"<html>\n  <head>\n    <style>\n{SLIDE_STYLE}\n    </style>\n  </head>\n  <body>\n"
            f"    <table>\n      <tr>\n{cells}\n      </tr>\n    </table>\n  </body>\n</html>\n")


def _preview(layout_name, t, mode, uid):
    """The schematic desktop of a layout as an SVG group, its ids made unique."""
    from jeronix_common import previews
    layout = json.loads((ROOT / "desktop" / "layouts" / f"{layout_name}.json").read_text(encoding="utf-8"))
    text = previews.layout_preview_svg(layout, t, mode)
    inner = text.split(">", 1)[1].rsplit("</svg>", 1)[0]
    return inner.replace("id='bg'", f"id='bg{uid}'").replace("url(#bg)", f"url(#bg{uid})"), \
        previews.W, previews.H


def _panel(x, y, w, h, t, mode, rows):
    """A panel opening from the taskbar, with rows of tiles or lines."""
    c, b = t["color"][mode], t["brand"]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{c["surface-raised"]}" '
           f'stroke="{c["border"]}" stroke-width="0.8"/>']
    for kind, ry, n in rows:
        if kind == "tiles":
            tw = (w - 16 - (n - 1) * 5) / n
            for i in range(n):
                fill = b["blue"] if i % 3 == 0 else c["surface-overlay"]
                out.append(f'<rect x="{x + 8 + i * (tw + 5):.1f}" y="{y + ry}" width="{tw:.1f}" height="16" '
                           f'rx="5" fill="{fill}"/>')
        elif kind == "apps":
            for i in range(n):
                fill = (b["blue"], b["sage"], c["text-muted"])[i % 3]
                out.append(f'<rect x="{x + 10 + i * 17:.1f}" y="{y + ry}" width="11" height="11" rx="3" '
                           f'fill="{fill}" opacity="0.9"/>')
        else:  # lines
            for i in range(n):
                out.append(f'<rect x="{x + 10}" y="{y + ry + i * 8}" width="{(w - 20) * (0.9 - i * 0.18):.1f}" '
                           f'height="3" rx="1.5" fill="{c["text"]}" opacity="{0.8 - i * 0.2:.2f}"/>')
    return "".join(out)


def slide_art(kind, t, mode="dark"):
    """The picture of a slide: 528 x 330 (or the J for the first)."""
    if kind == "hero":
        return hero(t, mode, 600)
    if kind == "foundation":
        return illustration("shield_checkmark", t, mode)
    w, h, scale = 528, 330, 1.65
    if kind == "layouts":
        # Side by side, in the order the slide names them.
        parts, s, gap = [], 0.52, 15
        for i, name in enumerate(("pure", "classic", "studio")):
            inner, pw, ph = _preview(name, t, mode, i)
            x, y = i * (pw * s + gap), (h - ph * s) / 2
            parts.append(f'<g transform="translate({x:g} {y:g}) scale({s})">{inner}</g>')
        return svg(w, h, "".join(parts))
    inner, pw, ph = _preview("pure", t, mode, 0)
    over = ""
    if kind == "start":  # the Start menu above the center module
        over = _panel(95, 28, 130, 130, t, mode, [("lines", 12, 1), ("apps", 26, 6), ("apps", 44, 6),
                                                  ("lines", 70, 3), ("lines", 104, 2)])
    elif kind == "widgets":  # the widgets above the left module
        over = _panel(6, 40, 110, 128, t, mode, [("lines", 12, 2), ("tiles", 34, 3), ("lines", 62, 3),
                                                 ("apps", 96, 3)])
    elif kind == "control":  # the Control Center above the tray
        over = _panel(200, 40, 114, 128, t, mode, [("tiles", 12, 2), ("tiles", 34, 2), ("tiles", 56, 2),
                                                   ("lines", 84, 3)])
    return svg(w, h, f'<g transform="scale({scale})">{inner}{over}</g>')


# -- whitelabel.yaml ----------------------------------------------------------------------

def whitelabel(t):
    b = t["brand"]
    lines = ["# JERONIX branding for Ubuntu's installer (generated by packaging/jeronix_installer.py).",
             "# Merged over the installer's own whitelabel.yml; images are in images/.",
             'app-name: "JERONIX Installer"',
             "theme:",
             "  light:",
             f'    accent-color: "{t["color"]["light"]["accent"]}"',
             f'    elevated-button-color: "{b["blue"]}"',
             '    elevated-button-text-color: "#FFFFFF"',
             "  dark:",
             f'    accent-color: "{t["color"]["dark"]["accent"]}"',
             f'    elevated-button-color: "{b["blue"]}"',
             '    elevated-button-text-color: "#FFFFFF"',
             "pages:"]
    for page, art in PAGES.items():
        name = {"logo": "logo", "hero": "hero", "mark": "mark"}.get(art, art)
        if art == "mark":
            lines += [f"  {page}:", f'    image: "{name}.svg"']
        else:
            lines += [f"  {page}:", f'    image: "{name}-light.svg"', f'    image-dark: "{name}-dark.svg"']
    return "\n".join(lines) + "\n"


def build(out, t=None):
    """Writes the installer branding into out (the desktop-provision
    directory). Returns the files written."""
    t = t or tokens()
    out = Path(out)
    files = {"whitelabel.yaml": whitelabel(t)}
    files["images/logo-light.svg"] = (ICONS / "jeronix-lockup-on-light.svg").read_text(encoding="utf-8")
    files["images/logo-dark.svg"] = (ICONS / "jeronix-lockup-on-dark.svg").read_text(encoding="utf-8")
    files["images/mark.svg"] = mark_icon()
    for mode in ("light", "dark"):
        files[f"images/hero-{mode}.svg"] = hero(t, mode)
        for art in sorted({a for a in PAGES.values() if a not in ("logo", "hero", "mark")}):
            files[f"images/{art}-{mode}.svg"] = illustration(art, t, mode)
    for n, (title, paragraphs, art) in enumerate(SLIDES, start=1):
        picture = f"{art}.svg"
        files[f"slides/{n}/{picture}"] = slide_art(art, t)
        files[f"slides/{n}/slide_en_US.html"] = slide_html(title, paragraphs, picture, art in ("hero", "foundation"))
    written = []
    for rel, text in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "installer"
    print(f"wrote {len(build(target))} files to {target}")
