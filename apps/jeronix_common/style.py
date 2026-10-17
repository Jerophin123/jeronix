# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX styling for libadwaita apps, generated from the design tokens.

libadwaita 1.9 exposes its palette as CSS custom properties (--window-bg-color,
--accent-bg-color, ...). JERONIX apps override them with token colors for the
current light/dark style and add a few JERONIX classes. Nothing here affects
other applications.
"""

import json

from . import paths


def load_tokens():
    return json.loads(paths.tokens_file().read_text(encoding="utf-8"))


def _rgba(hex_color, alpha):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def css_for(tokens, mode):
    """Application stylesheet for 'dark' or 'light'."""
    p = tokens["color"][mode]
    r = tokens["radius-px"]
    s = tokens["spacing-px"]
    variables = {
        "window-bg-color": p["surface"],
        "window-fg-color": p["text"],
        "view-bg-color": p["surface-raised"],
        "view-fg-color": p["text"],
        "headerbar-bg-color": p["surface"],
        "headerbar-fg-color": p["text"],
        "headerbar-backdrop-color": p["surface"],
        "sidebar-bg-color": p["surface-overlay"],
        "sidebar-fg-color": p["text"],
        "card-bg-color": p["surface-raised"],
        "card-fg-color": p["text"],
        "popover-bg-color": p["surface-raised"],
        "popover-fg-color": p["text"],
        "dialog-bg-color": p["surface-raised"],
        "dialog-fg-color": p["text"],
        "accent-bg-color": p["accent"],
        "accent-fg-color": p["on-accent"],
        "accent-color": p["accent-strong"],
        "success-color": p["success"],
        "warning-color": p["warning"],
        "error-color": p["danger"],
        "destructive-color": p["danger"],
        "border-color": _rgba(p["border"], 0.9),
    }
    lines = [":root {"] + [f"  --{k}: {v};" for k, v in variables.items()] + ["}"]
    lines += [
        # JERONIX classes used by the apps.
        f".jeronix-hero {{ font-size: {tokens['typography']['scale']['display']}em; font-weight: 700; }}",
        f".jeronix-subtitle {{ color: {p['text-muted']}; }}",
        f".jeronix-eyebrow {{ color: {p['accent-strong']}; font-weight: 700; font-size: 0.82em; }}",
        f".jeronix-tile {{ border-radius: {r['medium']}px; padding: {s['sm']}px; }}",
        f".jeronix-tile:hover {{ background-color: {_rgba(p['text'], tokens['interaction']['hover-opacity'])}; }}",
        f".jeronix-tile:selected, flowboxchild:selected .jeronix-tile {{ background-color: "
        f"{_rgba(p['accent'], tokens['interaction']['selected-opacity'])}; }}",
        f".jeronix-card {{ background-color: {p['surface-raised']}; border-radius: {r['large']}px; "
        f"border: 1px solid {p['border']}; padding: {s['md']}px; }}",
        f".jeronix-card.selected {{ border: 2px solid {p['accent']}; }}",
        f".jeronix-sidebar {{ background-color: {p['surface-overlay']}; }}",
        f".jeronix-search {{ font-size: 1.18em; min-height: 44px; border-radius: {r['medium']}px; }}",
        f".jeronix-key {{ font-family: monospace; padding: 2px {s['xs']}px; border-radius: {r['small']}px; "
        f"background-color: {p['surface-overlay']}; border: 1px solid {p['border']}; }}",
    ]
    return "\n".join(lines) + "\n"


def apply(application=None):
    """Installs the JERONIX stylesheet and keeps it in sync with light/dark.

    Call once after Adw.init() (i.e. in the application's startup)."""
    import gi
    gi.require_version("Adw", "1")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Adw, Gdk, Gtk

    tokens = load_tokens()
    manager = Adw.StyleManager.get_default()
    provider = Gtk.CssProvider()

    def sync(*_):
        provider.load_from_string(css_for(tokens, "dark" if manager.get_dark() else "light"))

    sync()
    manager.connect("notify::dark", sync)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    # Keep the provider alive with the application.
    if application is not None:
        application._jeronix_css = provider
    return provider
