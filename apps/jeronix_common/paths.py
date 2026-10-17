# SPDX-License-Identifier: GPL-3.0-or-later
"""Where JERONIX data lives, in a source checkout and when installed.

Installed layout (jeronix-desktop package, or install-desktop-dev.sh):
    <prefix>/jeronix/apps/...            this package
    <prefix>/jeronix/design/tokens.json  design tokens
    <prefix>/jeronix/layouts/*.json      layouts
    <prefix>/jeronix/scripts/jeronix_layout.py
where <prefix> is /usr/share or ~/.local/share. In a checkout, the repository
root plays the same role.
"""

import os
import sys
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parents[1]
_CHECKOUT = APPS_DIR.parent


def _installed_root():
    # apps/ sits directly in <prefix>/jeronix when installed.
    return APPS_DIR.parent if (APPS_DIR.parent / "layouts").is_dir() else None


def root():
    if (_CHECKOUT / "design" / "tokens" / "tokens.json").is_file():
        return _CHECKOUT
    return _installed_root() or _CHECKOUT


def tokens_file():
    r = root()
    for candidate in (r / "design" / "tokens" / "tokens.json", r / "design" / "tokens.json"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("JERONIX design tokens not found")


def layouts_dir():
    r = root()
    for candidate in (r / "desktop" / "layouts", r / "layouts"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("JERONIX layouts not found")


def layout_tool():
    """Imports scripts/jeronix_layout.py from the checkout or installation."""
    scripts = root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import jeronix_layout
    return jeronix_layout


def state_dir():
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    path = base / "jeronix"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extension_dirs(uuid):
    """Candidate directories of an installed GNOME Shell extension."""
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    bases = [data_home] + [Path(d) for d in system.split(":") if d]
    return [b / "gnome-shell" / "extensions" / uuid for b in bases]
