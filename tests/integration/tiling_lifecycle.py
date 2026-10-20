#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapping windows side by side with the JERONIX taskbar, in a real headless
GNOME Shell 50 (ubuntu session mode keeps Ubuntu's Tiling Assistant on, as on
an installed system; elsewhere GNOME's own edge tiling does the snapping).

Checks that a window snapped with Super+Left/Right, maximized with Super+Up
or dragged to a screen edge fits above the taskbar, which stays visible;
that dismissing the snap assist leaves no keyboard grab behind; that
applying the Pure layout never turns GNOME's tiling on next to Tiling
Assistant's; and that the shell logs nothing from the JERONIX extensions.

Usage: python3 tests/integration/tiling_lifecycle.py [--keep-logs]
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import harness
from layouts_lifecycle import LAYOUTS, TOOL, prepare

PANEL, DOCK = "jeronix-panel@jeronix", "jeronix-dock@jeronix"
THEME, QS = "jeronix-shell-theme@jeronix", "jeronix-quick-settings@jeronix"
TILING_ASSISTANT = "tiling-assistant@ubuntu.com"
WINDOW = str(Path(__file__).parent / "test_window.py")
SLACK = 2  # px: rounding of halves


def window(s, title):
    return next((w for w in s.state()["windows"] if w["title"] == title), None)


def inside(rect, area):
    x, y, w, h = rect
    ax, ay, aw, ah = area
    return x >= ax - SLACK and y >= ay - SLACK and x + w <= ax + aw + SLACK and y + h <= ay + ah + SLACK


def above_taskbar(s, title, what):
    """The window fits the work area, which ends above the visible taskbar."""
    st, dock = s.state(), s.debug(DOCK)
    rect, area = window(s, title)["rect"], st["workArea"]
    s.check(f"{what}: the window {rect} fits the work area {area}", inside(rect, area))
    s.check(f"{what}: the work area ends above the taskbar {dock['rect']}",
            area[1] + area[3] <= dock["rect"][1] + SLACK)
    s.check(f"{what}: the taskbar stays visible", dock["shown"])
    return rect, area


def dismiss(s, what):
    """Closes the snap assist (Tiling Assistant's window picker), if any:
    no keyboard grab may stay behind."""
    s.keys("Escape")
    s.wait_for(f"{what}: no grab left", lambda: s.state()["modalCount"] == 0, timeout=5)
    s.check(f"{what}: nothing holds the keyboard afterwards", True)


def snap(s, title, combo):
    s.window(title, "activate")
    time.sleep(0.4)
    s.keys(combo)
    time.sleep(1.2)


def drag(s, title, to):
    s.window(title, "activate")  # on top, so the press lands on its title bar
    time.sleep(0.5)
    x, y, w, _ = window(s, title)["rect"]
    sx, sy = x + w // 2, y + 18  # the title bar
    s.pointer(sx, sy)
    time.sleep(0.2)
    s.probe("PointerButton", (True,), "(b)")
    time.sleep(0.2)
    for i in range(1, 13):
        s.pointer(sx + (to[0] - sx) * i / 12, sy + (to[1] - sy) * i / 12)
        time.sleep(0.05)
    time.sleep(0.6)
    s.probe("PointerButton", (False,), "(b)")
    time.sleep(1.2)


def layout(*args):
    result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], env=dict(os.environ),
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"jeronix_layout {args[0]} failed: {result.stderr}")
    return result.stdout


def run(s):
    s.start()
    s.pointer(800, 500)
    assistant = s.state()["extensionStates"].get(TILING_ASSISTANT) == harness.STATE_ACTIVE
    print(f"# session mode: {s.mode}; snapping by {'Tiling Assistant' if assistant else 'GNOME'}")
    if not assistant:
        s.set_setting("org.gnome.mutter", "edge-tiling", "true")
    for uuid in (THEME, QS, PANEL, DOCK):
        s.enable(uuid)
    dock = s.debug(DOCK)
    s.check("by default the taskbar is the modules, always visible",
            (dock["style"], dock["behavior"]) == ("modules", "always"))
    s.spawn_client([sys.executable, WINDOW, "W1", "700", "450"])
    s.spawn_client([sys.executable, WINDOW, "W2", "600", "400"])
    s.wait_for("two windows", lambda: window(s, "W1") and window(s, "W2"))
    time.sleep(1)
    # The taskbar slides away in the overview (the shell starts in it) and
    # back on the desktop: the space it reserves must come back with it.
    s.overview(True)
    s.wait_for("overview", lambda: s.state()["overview"])
    s.overview(False)
    s.wait_for("desktop", lambda: not s.state()["overview"] and s.debug(DOCK)["shown"])
    time.sleep(0.8)
    area, dock = s.state()["workArea"], s.debug(DOCK)
    s.check(f"back from the overview, the taskbar reserves its space again ({area}, taskbar {dock['rect']})",
            area[1] + area[3] <= dock["rect"][1] + SLACK)

    # -- the keyboard ---------------------------------------------------------------
    snap(s, "W1", "Super+Left")
    (x, _, w, h), (ax, _, aw, ah) = above_taskbar(s, "W1", "Super+Left")
    s.check("Super+Left: the left half, full height", abs(x - ax) <= SLACK and abs(w - aw / 2) <= SLACK
            and abs(h - ah) <= SLACK)
    s.screenshot("20-snapped-left")
    dismiss(s, "Super+Left")
    snap(s, "W1", "Super+Right")
    (x, _, w, _), (ax, _, aw, _) = above_taskbar(s, "W1", "Super+Right")
    s.check("Super+Right: the right half", abs(x - (ax + aw / 2)) <= SLACK and abs(w - aw / 2) <= SLACK)
    dismiss(s, "Super+Right")
    snap(s, "W1", "Super+Up")
    s.wait_for("maximized", lambda: window(s, "W1")["maximized"], timeout=5)
    above_taskbar(s, "W1", "Super+Up (maximized)")
    dismiss(s, "Super+Up")
    s.window("W1", "unmaximize")
    time.sleep(0.8)

    # -- dragging to the edges ------------------------------------------------------------
    s.window("W1", "activate")
    mx, my, mw, mh = s.state()["monitor"]
    drag(s, "W1", (mx + 2, my + mh // 2))
    (x, _, w, _), (ax, _, aw, _) = above_taskbar(s, "W1", "dragged to the left edge")
    s.check("dragged to the left edge: the left half", abs(x - ax) <= SLACK and abs(w - aw / 2) <= SLACK)
    s.screenshot("21-dragged-left")
    dismiss(s, "dragged left")
    s.window("W1", "unmaximize")
    drag(s, "W2", (mx + mw - 3, my + mh // 2))
    (x, _, w, _), (ax, _, aw, _) = above_taskbar(s, "W2", "dragged to the right edge")
    s.check("dragged to the right edge: the right half", abs(x - (ax + aw / 2)) <= SLACK)
    dismiss(s, "dragged right")

    # -- the Pure layout leaves the snapping alone --------------------------------------------
    before = s.probe("GetSetting", ("org.gnome.mutter", "edge-tiling"), "(ss)")[0]
    out = layout("apply", LAYOUTS / "pure.json")
    s.check(f"Pure applied ({out.splitlines()[0]})", "applied layout" in out)
    time.sleep(1.5)
    after = s.probe("GetSetting", ("org.gnome.mutter", "edge-tiling"), "(ss)")[0]
    s.check(f"Pure does not touch GNOME's edge tiling ({before} -> {after})", before == after)
    s.window("W1", "unmaximize")
    snap(s, "W1", "Super+Left")
    above_taskbar(s, "W1", "Super+Left after Pure")
    dismiss(s, "after Pure")
    layout("restore")
    time.sleep(2)  # the taskbar rebuilds for the restored settings

    # JERONIX code paths, uuids and widgets.
    bad = s.shell_log_errors(["@jeronix", "jeronix-live", "jeronixDock", "JS ERROR"])
    for line in bad:
        print(f"  log: {line}")
    s.check("the shell logged nothing from the JERONIX extensions", not bad)


if __name__ == "__main__":
    sys.exit(harness.main(run, Path(__file__).resolve(), prefix="jeronix-tiling-", prepare=prepare,
                          keep_mode_extensions=(TILING_ASSISTANT,)))
