#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every page of JERONIX Settings on a real headless GNOME Shell 50.

The apps are staged as the installer does (packaging/jeronix_apps.py). For
each page, `settings.py --page ID` must open the window and keep running;
the sandbox has no Wi-Fi, Bluetooth, battery or printers, so the pages also
show how they look without that hardware. Afterwards the client log must hold
no Python errors. Screenshots of every page go to $JERONIX_SHOTS if set.

Screen brightness is checked end to end first: the shell's brightness
manager is given a screen with adjustable brightness (the headless shell has
none), and Settings' client must read it, set it, and follow changes made in
the shell, over the shell's D-Bus service.

Usage: python3 tests/integration/settings_pages.py [--keep-logs]
"""

import sys
import time
from pathlib import Path

import harness

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "apps"))
import jeronix_apps  # noqa: E402
from settings import catalog  # noqa: E402
from settings import system  # noqa: E402

TITLE = "JERONIX Settings"
EXTENSIONS = ("jeronix-shell-theme@jeronix", "jeronix-dock@jeronix", "jeronix-quick-settings@jeronix")


def prepare(tmp):
    jeronix_apps.stage(tmp / "data", python=sys.executable)


def window_open(s):
    return any(w["title"] == TITLE for w in s.state()["windows"])


def pumped(predicate):
    """predicate() after letting D-Bus signals reach this process."""
    from gi.repository import GLib
    context = GLib.MainContext.default()
    while context.iteration(False):
        pass
    return predicate()


def check_brightness(s):
    client = system.ShellBrightness()
    s.wait_for("brightness service", lambda: pumped(lambda: client.running))
    s.check("without a backlight, Settings is told brightness is not adjustable", not client.adjustable)

    s.probe("FakeBrightness", (True, 0.4), "(bd)")
    s.wait_for("adjustable brightness", lambda: pumped(lambda: client.adjustable))
    s.check(f"a backlight appearing is announced live (level {client.level:.2f})", abs(client.level - 0.4) < 1e-6)

    done = []
    client.set_level(0.75, lambda: done.append(True))
    s.wait_for("brightness set", lambda: pumped(lambda: done))
    s.check("Settings sets the shell's brightness",
            abs(s.probe("BrightnessValue")[0] - 0.75) < 1e-6)

    s.probe("FakeBrightness", (True, 0.2), "(bd)")  # keys, Quick Settings...
    s.wait_for("brightness followed", lambda: pumped(lambda: abs(client.level - 0.2) < 1e-6))
    s.check("changes made in the shell reach Settings live", True)

    client.set_level(1.7)  # out of range: clamped, never an error
    s.wait_for("clamped", lambda: pumped(lambda: abs(s.probe("BrightnessValue")[0] - 1.0) < 1e-6))
    s.check("out-of-range brightness is clamped", True)


def run(s):
    s.start()
    s.pointer(800, 500)
    for uuid in EXTENSIONS:
        s.enable(uuid)
    script = s.tmp / "data" / "jeronix" / "apps" / "settings" / "settings.py"
    check_brightness(s)  # leaves an adjustable screen for the Displays page
    for page in catalog.PAGE_IDS:
        proc = s.spawn_client([sys.executable, str(script), "--page", page])
        s.wait_for(f"Settings on {page}", lambda: window_open(s), timeout=30)
        time.sleep(2)  # let the page load its data and draw
        s.check(f"the {page} page opens and keeps running", proc.poll() is None)
        s.screenshot(f"settings-{page}")
        proc.terminate()
        proc.wait(10)
        s.wait_for("Settings closed", lambda: not window_open(s))

    # Displays again, on a screen without adjustable brightness.
    s.probe("FakeBrightness", (False, 0.0), "(bd)")
    proc = s.spawn_client([sys.executable, str(script), "--page", "displays"])
    s.wait_for("Settings on displays", lambda: window_open(s), timeout=30)
    time.sleep(2)
    s.check("the displays page opens without adjustable brightness", proc.poll() is None)
    s.screenshot("settings-displays-no-backlight")
    proc.terminate()
    proc.wait(10)
    s.wait_for("Settings closed", lambda: not window_open(s))

    errors = [line for line in (s.tmp / "client.log").read_text(errors="replace").splitlines()
              if "Traceback" in line or ("Error" in line and "Gdk-Message" not in line)
              or "CRITICAL" in line or "WARNING" in line]
    for line in errors:
        print(f"  client: {line}")
    s.check("no errors or warnings from Settings", not errors)


if __name__ == "__main__":
    sys.exit(harness.main(
        run, Path(__file__).resolve(),
        keyfile_extra="[org/gnome/desktop/interface]\ncolor-scheme='prefer-dark'\nenable-hot-corners=false",
        prefix="jeronix-settings-", prepare=prepare))
