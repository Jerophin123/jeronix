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


def placed(menu):
    """The open Start menu has been allocated (its rects are real numbers)."""
    return all(v is not None for k in ("rect", "footerRect") for v in (menu[k] or [None]))


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
    s.check("Windows 11-style Start, Search and Task View buttons lead the bar",
            dock["startButton"] and dock["searchButton"] and dock["taskViewButton"])
    gx, gy, gw, gh = dock["groupRect"]
    tx, ty, tw, th = dock["trayRect"]
    s.check(f"apps are centered on the taskbar (group {dock['groupRect']})", abs((gx + gw / 2) - (mx + mw / 2)) <= 2)
    s.check(f"the tray sits at the right end without overlapping the apps (tray {dock['trayRect']})",
            mx + mw - 24 <= tx + tw <= mx + mw and tx > gx + gw)
    s.check("the default is a full-width Windows 11 taskbar", dock["style"] == "taskbar" and x == mx and w == mw)
    state = s.state()
    s.check(f"Quick Settings and the clock/notification center are in the taskbar tray ({dock['tray']})",
            dock["tray"] == ["quickSettings", "dateMenu"]
            and state["quickSettingsParent"] == "jeronix-tray" and state["dateMenuParent"] == "jeronix-tray")
    s.check("GNOME's top bar is hidden while the taskbar carries the tray",
            dock["topBarHidden"] and state["panelVisible"] is False)

    # The tray grows (here: a longer clock); the apps must stay centered.
    s.set_setting("org.gnome.desktop.interface", "clock-show-seconds", "true")
    s.set_setting("org.gnome.desktop.interface", "clock-show-weekday", "true")
    wide = s.wait_for("wider tray", lambda: (d := s.debug(DOCK))["trayRect"][2] > tw + 20 and d)
    time.sleep(1)  # let the bar lay out again
    wide = s.debug(DOCK)
    gx, gy, gw, gh = wide["groupRect"]
    tx, ty, tw, th = wide["trayRect"]
    s.check(f"apps stay centered when the tray grows (tray {wide['trayRect']}, group {wide['groupRect']})",
            abs((gx + gw / 2) - (mx + mw / 2)) <= 2 and tx > gx + gw and tx + tw <= mx + mw)
    s.set_setting("org.gnome.desktop.interface", "clock-show-seconds", "false")
    s.set_setting("org.gnome.desktop.interface", "clock-show-weekday", "false")

    # Start menu (Windows 11): Super opens it, centered above the taskbar.
    s.keys("Super")
    start = s.wait_for("Start menu", lambda: (d := s.debug(DOCK))["startMenuOpen"] and placed(d["startMenu"]) and d)
    s.check("Super opens the JERONIX Start menu, not GNOME's overview",
            start["superKeyTaken"] and s.state()["overview"] is False)
    s.check("the Start menu shows the pinned apps",
            start["startMenuTitle"] == "Pinned" and start["startMenuApps"][:3] == FAVORITES)
    sx, sy, sw, sh = start["startMenu"]["rect"]
    s.check(f"the Start menu is centered on the screen ({start['startMenu']['rect']})",
            abs((sx + sw / 2) - (mx + mw / 2)) <= 2)
    s.check("the Start menu floats just above the taskbar", 0 <= y - (sy + sh) <= 24)
    fx, fy, fw, fh = start["startMenu"]["footerRect"]
    s.check(f"the footer spans the whole menu bottom ({start['startMenu']['footerRect']})",
            fx == sx and fw == sw and abs((fy + fh) - (sy + sh)) <= 1)
    s.check(f"the footer offers settings and power actions ({start['startMenu']['actions']})",
            start["startMenu"]["actions"][:2] == ["Settings", "Lock"])
    s.check("a Recommended section sits below the pinned apps", start["startMenu"]["recommendedVisible"])
    s.screenshot("01a-start-menu")
    for key in "text":
        s.keys(key)
    start = s.wait_for("search results", lambda: (d := s.debug(DOCK))["startMenuQuery"] == "text"
                       and d["startMenuTitle"] == "Best matches" and d)
    s.check(f"typing searches apps ({start['startMenuApps'][:2]})",
            start["startMenuApps"] and start["startMenuApps"][0] == "org.gnome.TextEditor.desktop")
    s.keys("Escape")
    s.wait_for("Start menu closed", lambda: not s.debug(DOCK)["startMenuOpen"])
    s.check("Escape closes the Start menu", True)

    # Super+J and the taskbar's Search box open the same Start menu.
    s.keys("Super+j")
    s.wait_for("Start menu from Super+J", lambda: s.debug(DOCK)["startMenuOpen"])
    s.check("Super+J opens the Start menu", True)
    s.keys("Super")
    s.wait_for("Start menu closed by Super", lambda: not s.debug(DOCK)["startMenuOpen"])
    s.check("Super closes the open Start menu", s.state()["overview"] is False)
    bx, by, bw, bh = s.debug(DOCK)["searchRect"]
    s.click(bx + bw / 2, by + bh / 2)
    s.wait_for("Start menu from Search", lambda: s.debug(DOCK)["startMenuOpen"])
    s.check("the Search box opens the Start menu search, not GNOME's overview", s.state()["overview"] is False)
    s.screenshot("01c-search")
    s.keys("Escape")
    s.wait_for("Start menu closed", lambda: not s.debug(DOCK)["startMenuOpen"])

    # macOS-style magnification and label on a favorite that is not running.
    fx, fy, fw, fh = dock["itemRects"][1]
    s.pointer(fx + fw / 2 - 3, fy + fh / 2)
    s.pointer(fx + fw / 2, fy + fh / 2)
    mag = s.wait_for("magnification", lambda: (d := s.debug(DOCK))["magnification"][FAVORITES[1]] > 1.15 and d)
    s.check("the hovered icon is magnified and its neighbors grow less",
            1.03 < mag["magnification"][FAVORITES[0]] < 1.12 and 1.03 < mag["magnification"][FAVORITES[2]] < 1.12)
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
    dash = s.state()["overviewDash"]
    s.check(f"Task View shows no GNOME dash or app grid button ({dash})",
            dash["visible"] is False and dash["height"] == 0 and s.debug(DOCK)["overviewDashHidden"])
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
    state = s.state()
    s.check("disabling the dock puts Quick Settings and the clock back in GNOME's top bar",
            state["panelVisible"] is True and state["quickSettingsParent"] == "panelRight"
            and state["dateMenuParent"] == "panelCenter")
    s.check("disabling the dock gives the overview its dash back", state["overviewDash"]["visible"] is True)
    s.keys("Super")
    s.wait_for("overview from Super", lambda: s.state()["overview"])
    s.check("disabling the dock gives the Super key back to GNOME's overview", True)
    s.overview(False)
    s.wait_for("overview closed", lambda: not s.state()["overview"])
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
