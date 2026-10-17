#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX desktop shell in a real headless GNOME Shell 50 (ubuntu session
mode, Yaru underneath): panel, dock, theme and Stay Awake together.

Checks behavior through the extensions' debugState() and the shell's real
window list, drives the pointer with a virtual input device, and, when
JERONIX_SHOTS=DIR is set, saves screenshots of each stage for review.

Usage: python3 tests/integration/desktop_lifecycle.py [--keep-logs]
"""

import sys
import time
from pathlib import Path

import harness

PANEL, DOCK = "jeronix-panel@jeronix", "jeronix-dock@jeronix"
THEME, QS = "jeronix-shell-theme@jeronix", "jeronix-quick-settings@jeronix"
FAVORITES = ["org.gnome.Nautilus.desktop", "org.gnome.TextEditor.desktop", "org.gnome.Settings.desktop"]
TEST_APP = "io.jeronix.TestWindow.desktop"
TITLE = "JERONIX Test Window"
MARGIN = 12

DESKTOP_FILE = f"""[Desktop Entry]
Type=Application
Name=JERONIX Test Window
Exec={sys.executable} {Path(__file__).parent / 'test_window.py'}
Icon=applications-utilities
StartupWMClass=io.jeronix.TestWindow
"""


def run(s):
    s.start()
    print(f"# session mode: {s.mode}")
    s.pointer(800, 500)  # the virtual pointer starts in the hot corner
    for uuid in (THEME, QS, PANEL, DOCK):
        s.enable(uuid)

    # -- panel -------------------------------------------------------------
    panel = s.debug(PANEL)
    s.check("JERONIX menu button is in the top bar", panel["menuButton"])
    s.check("Activities button is replaced", panel["activitiesVisible"] is False)
    for label in ("Search Applications", "Overview", "Layout Studio", "System Information"):
        s.check(f"menu offers '{label}'", label in panel["menuItems"])
    s.check("workspace switcher matches the shell", panel["workspaces"] == s.state()["workspaces"])

    # -- dock: favorites and placement ---------------------------------------
    dock = s.wait_for("dock items", lambda: (d := s.debug(DOCK)) and d["items"] and d)
    s.check(f"dock shows the favorites in order {dock['items']}", dock["items"] == FAVORITES)
    mx, my, mw, mh = dock["monitor"]
    x, y, w, h = dock["rect"]
    s.check("dock is centered at the bottom with a floating margin",
            abs((x + w / 2) - (mx + mw / 2)) <= 1 and y + h == my + mh)
    s.check("dock is visible on an empty desktop (intellihide)", dock["shown"] and dock["visible"])
    s.screenshot("01-desktop")

    # -- running app, panel context, previews --------------------------------
    s.spawn_client([sys.executable, str(Path(__file__).parent / "test_window.py"), TITLE, "720", "460"])
    s.wait_for("test window", lambda: any(w["title"] == TITLE for w in s.state()["windows"]))
    dock = s.wait_for("running app in dock", lambda: TEST_APP in s.debug(DOCK)["items"] and s.debug(DOCK))
    s.check("running non-favorite app is appended after favorites", dock["items"][-1] == TEST_APP)
    s.wait_for("focused app in panel", lambda: s.debug(PANEL)["focusedApp"] == "JERONIX Test Window")
    s.check("panel shows the focused application", True)

    # Hover the running app's icon: previews open after a short delay.
    s.check("no scrollbar when every app fits", dock["overflow"] is False)
    s.check("Windows 11-style Start and Search buttons lead the bar",
            dock["startButton"] and dock["searchButton"])

    # macOS-style magnification and label on a favorite that is not running.
    fx, fy, fw, fh = dock["itemRects"][1]
    s.pointer(fx + fw / 2 - 3, fy + fh / 2)
    s.pointer(fx + fw / 2, fy + fh / 2)
    mag = s.wait_for("magnification", lambda: (d := s.debug(DOCK))["magnification"][FAVORITES[1]] > 1.3 and d)
    s.check("the hovered icon is magnified and its neighbors grow less",
            1.1 < mag["magnification"][FAVORITES[0]] < 1.2 and 1.1 < mag["magnification"][FAVORITES[2]] < 1.2)
    label = s.wait_for("hover label", lambda: s.debug(DOCK)["label"])
    s.check(f"a label with the app name appears above the icon ({label!r})", label == "Text Editor")
    s.screenshot("01b-magnify")
    s.pointer(mx + mw / 2, my + mh / 3)
    s.wait_for("magnification reset", lambda: all(v == 1 for v in s.debug(DOCK)["magnification"].values()))
    s.check("leaving the dock restores icon sizes and hides the label", s.debug(DOCK)["label"] is None)
    ix, iy, iw, ih = dock["itemRects"][0]
    x, y, w, h = dock["rect"]
    s.check(f"dock container hugs the dock ({h}px = items {ih}px + padding + margin)", h <= ih + 2 * 8 + 2 + MARGIN + 2)
    ix, iy, iw, ih = dock["itemRects"][dock["items"].index(TEST_APP)]
    s.pointer(ix + iw / 2 - 3, iy + ih / 2 - 3)
    s.pointer(ix + iw / 2, iy + ih / 2)
    s.wait_for("window previews", lambda: s.debug(DOCK)["previewsOpen"])
    s.check("hovering a running app opens its window previews", True)
    s.screenshot("02-previews")
    s.pointer(mx + mw / 2, my + mh / 3)
    s.wait_for("previews closed", lambda: not s.debug(DOCK)["previewsOpen"])
    s.check("previews close when the pointer leaves", True)

    # -- intellihide ------------------------------------------------------------
    s.window(TITLE, "maximize")
    s.wait_for("dock hides for a maximized window", lambda: not s.debug(DOCK)["shown"], timeout=10)
    s.check("intellihide hides the dock when a window overlaps it", True)
    s.screenshot("03-maximized")
    s.pointer(mx + mw / 2, my + mh - 1)
    s.wait_for("dock revealed at the edge", lambda: s.debug(DOCK)["shown"], timeout=10)
    s.check("touching the screen edge reveals the hidden dock", True)
    s.pointer(mx + mw / 2, my + mh / 3)
    s.wait_for("dock hides again", lambda: not s.debug(DOCK)["shown"], timeout=10)
    s.check("the dock hides again when the pointer leaves", True)
    s.window(TITLE, "unmaximize")
    s.wait_for("dock back", lambda: s.debug(DOCK)["shown"], timeout=10)
    s.check("the dock returns when nothing overlaps it", True)

    # -- overview -------------------------------------------------------------
    s.overview(True)
    s.check("the dock steps aside for the overview (no second dock)", not s.debug(DOCK)["shown"])
    s.screenshot("04-overview")
    s.overview(False)
    s.wait_for("dock after overview", lambda: s.debug(DOCK)["shown"])

    # -- position and behavior settings ---------------------------------------
    s.set_ext(DOCK, "position", "'left'")
    dock = s.wait_for("left dock", lambda: (d := s.debug(DOCK)) and d["position"] == "left" and d)
    x, y, w, h = dock["rect"]
    s.check("position=left places the dock on the left edge", x == mx and dock["items"][:3] == FAVORITES)
    s.screenshot("05-dock-left")
    s.set_ext(DOCK, "position", "'right'")
    dock = s.wait_for("right dock", lambda: (d := s.debug(DOCK)) and d["position"] == "right" and d)
    x, y, w, h = dock["rect"]
    s.check("position=right places the dock on the right edge", x + w == mx + mw)
    s.set_ext(DOCK, "position", "'bottom'")
    s.set_ext(DOCK, "behavior", "'always'")
    s.window(TITLE, "maximize")
    time.sleep(1)
    win = next(w for w in s.state()["windows"] if w["title"] == TITLE)
    dock = s.debug(DOCK)
    s.check("behavior=always keeps the dock and reserves its space (maximized window ends above it)",
            dock["shown"] and win["rect"][1] + win["rect"][3] <= dock["rect"][1])
    s.set_ext(DOCK, "behavior", "'intellihide'")
    s.window(TITLE, "unmaximize")

    # -- light variant ----------------------------------------------------------
    s.probe("SetColorScheme", ("prefer-light",), "(s)")
    time.sleep(1)
    s.screenshot("06-light")
    s.probe("SetColorScheme", ("prefer-dark",), "(s)")

    # -- Stay Awake still there --------------------------------------------------
    count = s.probe("FindToggles", ("Stay Awake",), "(s)")[0]
    s.check("Stay Awake toggle is still present with the JERONIX shell", count == 1)

    # -- teardown -----------------------------------------------------------------
    s.disable(DOCK)
    s.check("disabling the dock removes it", s.debug(DOCK) is None)
    s.disable(PANEL)
    s.check("disabling the panel restores the Activities button",
            s.debug(PANEL) is None and s.state()["activitiesVisible"] is True)
    s.screenshot("07-restored")
    bad = s.shell_log_errors([f"{PANEL}/", f"{DOCK}/", "jeronix-panel", "jeronix-dock"])
    for line in bad:
        print(f"  log: {line}")
    s.check("no errors from JERONIX extensions in the shell log", not bad)


if __name__ == "__main__":
    favorites = ", ".join(f"'{f}'" for f in FAVORITES)
    sys.exit(harness.main(
        run, Path(__file__).resolve(),
        keyfile_extra=(f"favorite-apps=[{favorites}]\n[org/gnome/desktop/interface]\n"
                       "color-scheme='prefer-dark'\nenable-hot-corners=false"),
        desktop_files=[(TEST_APP, DESKTOP_FILE)],
        prefix="jeronix-desktop-"))
