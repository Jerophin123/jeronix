#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Layouts in a real headless GNOME Shell 50 with Ubuntu's dock running.

Applies Pure, Studio and Classic with scripts/jeronix_layout.py (the same
code Layout Studio and Welcome use) and checks that the shell follows: the
JERONIX dock replaces Ubuntu's (never both), dock position and workspaces
change, and restoring the snapshots returns to Ubuntu's dock exactly.

Usage: python3 tests/integration/layouts_lifecycle.py [--keep-logs]
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import harness

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "jeronix_layout.py"
LAYOUTS = ROOT / "desktop" / "layouts"
UBUNTU_DOCK, DOCK, PANEL = "ubuntu-dock@ubuntu.com", "jeronix-dock@jeronix", "jeronix-panel@jeronix"


def prepare(tmp):
    """Installs the assets layouts refer to: wallpapers and the icon theme."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import jeronix_design
    import jeronix_icons
    tokens = jeronix_design.load_tokens()
    jeronix_design.build_wallpapers(tokens, tmp / "assets", sizes=((1920, 1080),))
    walls = tmp / "data" / "backgrounds" / "jeronix"
    walls.mkdir(parents=True)
    for mode in ("dark", "light"):
        shutil.copyfile(tmp / "assets" / "wallpapers" / f"jeronix-{mode}-1920x1080.png", walls / f"jeronix-{mode}.png")
    jeronix_icons.build(tokens, tmp / "data")


def layout(s, action, *args):
    result = subprocess.run([sys.executable, str(TOOL), action, *map(str, args)], env=dict(os.environ),
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"jeronix_layout {action} failed: {result.stderr}")
    return result.stdout


def active(s, uuid):
    return s.ext_state(uuid)[0] == harness.STATE_ACTIVE


def wait_docks(s, jeronix):
    """Waits until exactly one dock runs; never both at once."""
    seen_both = False
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        u, j = active(s, UBUNTU_DOCK), active(s, DOCK)
        seen_both |= u and j
        if j == jeronix and u != jeronix:
            return seen_both
        time.sleep(0.1)
    raise AssertionError(f"docks did not settle (ubuntu={active(s, UBUNTU_DOCK)}, jeronix={active(s, DOCK)})")


def run(s):
    s.start()
    s.pointer(800, 500)
    if s.mode != "ubuntu":
        print("# not an Ubuntu session mode: Ubuntu Dock checks are skipped")
    else:
        s.wait_for("Ubuntu Dock running", lambda: active(s, UBUNTU_DOCK))
        s.check("before any layout, Ubuntu Dock runs and the JERONIX dock does not",
                not active(s, DOCK))
        s.screenshot("10-ubuntu-before")

    expectations = [
        ("pure", "bottom", "always", None),
        ("studio", "right", "autohide", 4),
        ("classic", "bottom", "always", None),
    ]
    for name, position, behavior, workspaces in expectations:
        out = layout(s, "apply", LAYOUTS / f"{name}.json")
        s.check(f"[{name}] applied ({out.splitlines()[0]})", "applied layout" in out)
        if s.mode == "ubuntu":
            both = wait_docks(s, jeronix=True)
            s.check(f"[{name}] the JERONIX dock replaced Ubuntu Dock without both showing", not both)
        else:
            s.wait_for("JERONIX dock", lambda: active(s, DOCK))
        dock = s.wait_for(f"{name} dock", lambda: (d := s.debug(DOCK)) and d["position"] == position and d)
        s.check(f"[{name}] dock is at the {position} edge with '{behavior}' behavior",
                dock["behavior"] == behavior)
        s.wait_for(f"{name} top bar", lambda: active(s, PANEL))
        s.check(f"[{name}] JERONIX top bar is active", True)
        if workspaces:
            s.wait_for("fixed workspaces", lambda: s.state()["workspaces"] == workspaces)
            s.check(f"[{name}] {workspaces} fixed workspaces", True)
        time.sleep(1)
        s.screenshot(f"11-layout-{name}")

    snapshots = layout(s, "snapshots").split()
    s.check("one snapshot per applied layout", len(snapshots) == 3)
    for snap in reversed(snapshots):
        layout(s, "restore", snap)
    if s.mode == "ubuntu":
        wait_docks(s, jeronix=False)
        s.check("restoring every snapshot brings Ubuntu Dock back and stops the JERONIX dock", True)
    s.wait_for("panel off", lambda: not active(s, PANEL))
    s.check("the JERONIX top bar is off again after restoring", True)
    time.sleep(1)
    s.screenshot("12-ubuntu-restored")
    bad = s.shell_log_errors(["jeronix-panel", "jeronix-dock", "jeronix-shell-theme"])
    for line in bad:
        print(f"  log: {line}")
    s.check("no errors from JERONIX extensions while switching layouts", not bad)


if __name__ == "__main__":
    sys.exit(harness.main(
        run, Path(__file__).resolve(),
        keyfile_extra="[org/gnome/desktop/interface]\nenable-hot-corners=false",
        prefix="jeronix-layouts-", prepare=prepare,
        keep_mode_extensions=(UBUNTU_DOCK,)))
