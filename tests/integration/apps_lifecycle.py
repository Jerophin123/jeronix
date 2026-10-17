#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX applications on a real headless GNOME Shell 50 (ubuntu session
mode, JERONIX shell enabled).

The apps are staged exactly as the installer does (packaging/jeronix_apps.py)
into the sandbox's data directory. Each one must open its window, show the
right name in the top bar and keep running; Super+Shift+J must open the launcher
through the panel's keybinding. Screenshots go to $JERONIX_SHOTS if set.

Usage: python3 tests/integration/apps_lifecycle.py [--keep-logs]
"""

import sys
import time
from pathlib import Path

import harness

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))
import jeronix_apps  # noqa: E402

PANEL = "jeronix-panel@jeronix"
APPS = [
    # (script relative to the staged apps dir, window title, panel name)
    ("launcher/launcher.py", "JERONIX Launcher", "JERONIX Launcher"),
    ("layout_studio/studio.py", "JERONIX Layout Studio", "Layout Studio"),
    ("settings/settings.py", "JERONIX Settings", "JERONIX Settings"),
    ("system_info/sysinfo.py", "JERONIX System Information", "System Information"),
    ("welcome/welcome.py", "Welcome to JERONIX", "Welcome to JERONIX"),
]
EXTENSIONS = ("jeronix-shell-theme@jeronix", PANEL, "jeronix-dock@jeronix")


def prepare(tmp):
    jeronix_apps.stage(tmp / "data", python=sys.executable)


def window_open(s, title):
    return any(w["title"] == title for w in s.state()["windows"])


def run(s):
    s.start()
    s.pointer(800, 500)
    for uuid in EXTENSIONS:
        s.enable(uuid)
    apps_dir = s.tmp / "data" / "jeronix" / "apps"

    for script, title, panel_name in APPS:
        proc = s.spawn_client([sys.executable, str(apps_dir / script)])
        s.wait_for(f"{title} window", lambda: window_open(s, title), timeout=30)
        time.sleep(1.5)
        s.check(f"{title} opens its window and keeps running", proc.poll() is None)
        s.wait_for(f"{panel_name} in the top bar", lambda: s.debug(PANEL)["focusedApp"] == panel_name)
        s.check(f"the top bar names it '{panel_name}' (desktop entry matched)", True)
        s.screenshot(Path(script).stem)
        proc.terminate()
        proc.wait(10)
        s.wait_for(f"{title} closed", lambda: not window_open(s, title))

    # The panel's Super+Shift+J keybinding launches the launcher via its desktop entry
    # (Super+J opens the Start menu, tested in desktop_lifecycle.py).
    s.keys("Super+Shift+j")
    s.wait_for("launcher from Super+Shift+J", lambda: window_open(s, "JERONIX Launcher"), timeout=30)
    s.check("Super+Shift+J opens the JERONIX Launcher", True)

    errors = [line for line in (s.tmp / "client.log").read_text(errors="replace").splitlines()
              if "Traceback" in line or ("Error" in line and "Gdk-Message" not in line)]
    for line in errors:
        print(f"  client: {line}")
    s.check("no Python errors from the applications", not errors)


if __name__ == "__main__":
    sys.exit(harness.main(
        run, Path(__file__).resolve(),
        keyfile_extra=("favorite-apps=['org.gnome.Nautilus.desktop', 'org.gnome.TextEditor.desktop']\n"
                       "[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-hot-corners=false"),
        prefix="jeronix-apps-", prepare=prepare))
