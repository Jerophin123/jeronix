#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX desktop shell in a real headless GNOME Shell 50 (ubuntu session
mode, Yaru underneath): panel, dock, theme and Stay Awake together.

Checks behavior through the extensions' debugState() and the shell's real
window list, drives the pointer with a virtual input device, and, when
JERONIX_SHOTS=DIR is set, saves screenshots of each stage for review.

Usage: python3 tests/integration/desktop_lifecycle.py [--keep-logs]
"""

import subprocess
import sys
import time
from pathlib import Path

import harness

PANEL, DOCK = "jeronix-panel@jeronix", "jeronix-dock@jeronix"
THEME, QS = "jeronix-shell-theme@jeronix", "jeronix-quick-settings@jeronix"
CC_DEFAULT = ["wifi", "bluetooth", "airplane-mode", "vpn", "focus", "stay-awake", "dark-mode", "night-light",
              "power-mode", "display", "sound", "now-playing", "battery", "screenshot", "screen-recording", "settings"]
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
    """The open Start menu has been laid out (its rects are real numbers and
    the footer has its final width: the panel is restyled as it opens)."""
    if not all(v is not None for k in ("rect", "footerRect") for v in (menu[k] or [None])):
        return False
    return abs(menu["footerRect"][2] - menu["rect"][2]) <= 1


class FakePlayer:
    """A media player (MPRIS) on the test's session bus, for the live updates.
    The test process answers its D-Bus calls while it waits (pumped())."""

    XML = """<node><interface name="org.mpris.MediaPlayer2.Player">
      <method name="PlayPause"/><method name="Next"/><method name="Previous"/>
      <property name="PlaybackStatus" type="s" access="read"/>
      <property name="Metadata" type="a{sv}" access="read"/>
      <property name="CanGoNext" type="b" access="read"/>
      <property name="CanGoPrevious" type="b" access="read"/>
    </interface></node>"""
    PATH = "/org/mpris/MediaPlayer2"

    def __init__(self, s):
        self.Gio, self.GLib = s.Gio, s.GLib
        self.bus = s.bus
        self.status = "Playing"
        self.calls = []
        info = self.Gio.DBusNodeInfo.new_for_xml(self.XML).interfaces[0]
        self.registration = self.bus.register_object(self.PATH, info, self._call, self._get, None)
        self.owner = self.Gio.bus_own_name_on_connection(self.bus, "org.mpris.MediaPlayer2.jeronixtest",
                                                         self.Gio.BusNameOwnerFlags.NONE, None, None)

    def _call(self, conn, sender, path, iface, method, params, invocation):
        self.calls.append(method)
        if method == "PlayPause":
            self.status = "Paused" if self.status == "Playing" else "Playing"
            v = self.GLib.Variant
            self.bus.emit_signal(None, self.PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 v("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player",
                                                  {"PlaybackStatus": v("s", self.status)}, [])))
        invocation.return_value(None)

    def _get(self, conn, sender, path, iface, prop):
        v = self.GLib.Variant
        return {"PlaybackStatus": v("s", self.status),
                "Metadata": v("a{sv}", {"xesam:title": v("s", "Test Song"), "xesam:artist": v("as", ["JERONIX"])}),
                "CanGoNext": v("b", True), "CanGoPrevious": v("b", True)}[prop]

    def close(self):
        self.Gio.bus_unown_name(self.owner)
        self.bus.unregister_object(self.registration)


def pumped(s, predicate):
    """predicate() after this process has answered pending D-Bus calls."""
    context = s.GLib.MainContext.default()
    while context.iteration(False):
        pass
    return predicate()


def live(s):
    return s.debug(DOCK)["live"]


def check_live_updates(s, mx, mw):
    """Live updates and widgets in the free left end of the taskbar."""
    lv = s.wait_for("live updates", lambda: (l := live(s)) and l["placed"] and l)
    lx, ly, lw, lh = lv["rect"]
    gx = s.debug(DOCK)["groupRect"][0]
    s.check(f"live updates sit at the left end of the taskbar, clear of the apps ({lv['rect']})",
            mx <= lx <= mx + 24 and lx + lw < gx)
    s.check(f"with nothing going on they offer the widgets ({lv['labels']})",
            lv["kind"] == "idle" and "Widgets" in lv["labels"])

    # A brightness change (keys, Quick Settings) shows for a moment, once
    # the first moments after starting (no updates at login) are over.
    s.wait_for("level updates", lambda: live(s)["levelsShown"])
    s.probe("FakeBrightness", (True, 0.5), "(bd)")
    time.sleep(0.5)
    s.probe("FakeBrightness", (True, 0.8), "(bd)")
    lv = s.wait_for("brightness update", lambda: (l := live(s))["kind"] == "level" and l)
    s.check(f"a brightness change shows live ({lv['labels']})", "Brightness" in lv["labels"] and "80%" in lv["labels"])
    s.wait_for("brightness update ends", lambda: live(s)["kind"] == "idle", timeout=6)
    s.check("the update goes away by itself", True)
    s.probe("FakeBrightness", (False, 0.0), "(bd)")

    # A notification shows its app and title.
    s.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
           "Notify", ("JERONIX Test", 0, "dialog-information-symbolic", "Backup finished", "All files are safe",
                      [], {}, 5000), "(susssasa{sv}i)")
    lv = s.wait_for("notification update", lambda: (l := live(s))["kind"] == "notification" and l)
    s.check(f"a new notification shows live ({lv['labels']})",
            "Backup finished" in lv["labels"] and "All files are safe" in lv["labels"])
    s.screenshot("01e-live-notification")
    s.wait_for("notification update ends", lambda: live(s)["kind"] == "idle", timeout=10)

    # Music: shown while it plays, with play/pause right there.
    player = FakePlayer(s)
    try:
        lv = s.wait_for("music", lambda: pumped(s, lambda: (l := live(s))["kind"] == "media" and l))
        s.check(f"playing music shows live ({lv['labels']})", "Test Song" in lv["labels"] and "JERONIX" in lv["labels"])
        s.check("with a pause button", lv["button"] and lv["button"]["name"] == "Pause")
        s.screenshot("01f-live-music")
        # Coordinates exist once the redrawn area has been laid out.
        lv = s.wait_for("laid out", lambda: pumped(s, lambda: (l := live(s))["button"]
                                                     and None not in l["button"]["rect"] and l))
        bx, by, bw, bh = lv["button"]["rect"]
        s.click(bx + bw / 2, by + bh / 2)
        s.wait_for("paused", lambda: pumped(s, lambda: player.status == "Paused"
                                              and live(s)["button"]["name"] == "Play"))
        s.check(f"pause in the taskbar pauses the player ({player.calls})", player.calls == ["PlayPause"])
        s.check("a paused song stays for a while", live(s)["kind"] == "media")

        # Stay Awake (higher than music? no: music is more interesting).
        # The widgets panel opens from the area.
        lv = live(s)
        lx, ly, lw, lh = lv["rect"]
        s.click(lx + 12, ly + lh / 2)
        lv = s.wait_for("widgets open", lambda: pumped(s, lambda: (l := live(s))["panelOpen"] and l))
        s.check(f"clicking opens the widgets ({lv['widgets']})",
                lv["widgets"] == ["clock", "timer", "media", "system"]
                and "battery" not in lv["widgets"])
        s.check("the taskbar stays up while the widgets are open", s.debug(DOCK)["shown"])
        time.sleep(2.5)  # the system widget measures CPU use over time
        s.screenshot("01g-widgets")
        s.keys("Escape")
        s.wait_for("widgets closed", lambda: not live(s)["panelOpen"])
    finally:
        player.close()
    s.wait_for("music gone", lambda: pumped(s, lambda: live(s)["kind"] == "idle"))
    s.check("closing the player ends its update", True)

    # Stay Awake shows while it is on (it needs a session manager to hold
    # its inhibitor; the test bus has none, so a stand-in is started).
    fake = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_session_manager.py")])
    try:
        s.wait_for("session manager", lambda: s.has_name("org.gnome.SessionManager"))
        s.probe("ClickToggle", ("Stay Awake",), "(s)")
        lv = s.wait_for("stay awake", lambda: (l := live(s))["kind"] == "stay-awake" and l)
        s.check(f"Stay Awake shows live ({lv['labels']})", "Stay Awake" in lv["labels"])
        s.probe("ClickToggle", ("Stay Awake",), "(s)")
        s.wait_for("stay awake off", lambda: live(s)["kind"] == "idle")
    finally:
        fake.terminate()
        fake.wait(10)

    # The widget list follows Settings live; the whole area can be turned off.
    s.set_ext(DOCK, "live-widgets", "['system', 'clock']")
    lv = live(s)
    lx, ly, lw, lh = lv["rect"]
    s.click(lx + 12, ly + lh / 2)
    lv = s.wait_for("widgets open", lambda: (l := live(s))["panelOpen"] and l)
    s.check(f"the chosen widgets show, in order ({lv['widgets']})", lv["widgets"] == ["system", "clock"])
    s.keys("Escape")
    s.wait_for("widgets closed", lambda: not live(s)["panelOpen"])
    s.set_ext(DOCK, "live-widgets", "['clock', 'timer', 'media', 'weather', 'system', 'battery']")
    s.set_ext(DOCK, "live-updates", "false")
    s.wait_for("live updates off", lambda: (d := s.debug(DOCK)) and d["live"] is None)
    s.check("live updates can be turned off", True)
    s.set_ext(DOCK, "live-updates", "true")
    s.wait_for("live updates back", lambda: (d := s.debug(DOCK)) and d["live"] and d["live"]["placed"])
    s.check("and on again", True)


MODULE_MARGIN = 8  # desktop/extensions/jeronix-dock/modules.js


def modules(s):
    return s.debug(DOCK)["modules"]


def check_module_opens(s, side, open_it, close_it, shot, what):
    """Opening a panel expands its module, and the panel stands on it."""
    rest = modules(s)["rects"][side]
    open_it()
    m = s.wait_for(f"{what} expanded", lambda: (m := modules(s)) and m["expansion"].get(side) == 1
                   and side in m["panels"] and m)
    time.sleep(0.4)  # the panel's own opening animation
    m = modules(s)
    mx_, my_, mw_, mh_ = m["rects"][side]
    px, py, pw, ph = m["panels"][side]["rect"]
    s.check(f"{what}: the {side} module expands toward its panel (module {rest} -> {m['rects'][side]})",
            mw_ >= rest[2] and (mw_ > rest[2] or pw <= rest[2]))
    s.check(f"{what}: the panel stands directly on the module (panel bottom {py + ph}, module top {my_})",
            abs((py + ph) - my_) <= 1)
    if side == "left":
        edge = abs(px - mx_) <= 1
    elif side == "right":
        edge = abs((px + pw) - (mx_ + mw_)) <= 1
    else:
        edge = abs((px + pw / 2) - (mx_ + mw_ / 2)) <= 1
    s.check(f"{what}: the panel lines up with the module ({m['panels'][side]['rect']} on {m['rects'][side]})", edge)
    shape = next(c for c in ("jeronix-fused", "jeronix-flush-left", "jeronix-flush-right", "jeronix-floating")
                 if c in m["classes"][side])
    s.check(f"{what}: module and panel share one shape ({shape})",
            shape in m["panels"][side]["classes"] and "jeronix-module-open" in m["classes"][side]
            and (shape != "jeronix-fused" or abs(pw - mw_) <= 1))
    s.screenshot(shot)
    close_it()
    m = s.wait_for(f"{what} collapsed", lambda: (m := modules(s)) and side not in m["open"]
                   and m["expansion"].get(side, 0) == 0 and m)
    # (The left module's resting width follows what the live updates show,
    # which may have changed meanwhile: compare with the panel instead.)
    s.check(f"{what}: closing it shrinks the module back ({m['rects'][side]})",
            m["rects"][side][2] < pw - 1 and "jeronix-module-open" not in m["classes"][side])


def check_modules(s, mx, mw):
    """The taskbar as three expandable modules."""
    m = s.wait_for("modules", lambda: modules(s))
    left, center, right = (m["rects"][k] for k in ("left", "center", "right"))
    s.check(f"three modules: live updates {left}, Start and apps {center}, tray {right}",
            left[0] == mx + MODULE_MARGIN and right[0] + right[2] == mx + mw - MODULE_MARGIN
            and left[0] + left[2] < center[0] and center[0] + center[2] < right[0])
    s.check("the modules float, with the same height", left[3] == center[3] == right[3] > 0)
    s.check("the app module is centered", abs((center[0] + center[2] / 2) - (mx + mw / 2)) <= 2)

    def click_live():
        lx, ly, lw, lh = s.debug(DOCK)["live"]["rect"]
        s.click(lx + 12, ly + lh / 2)

    check_module_opens(s, "left", click_live, lambda: s.keys("Escape"), "08a-module-widgets", "Widgets")
    check_module_opens(s, "center", lambda: s.keys("Super"), lambda: s.keys("Escape"), "08b-module-start",
                       "Start")
    check_module_opens(s, "right", lambda: s.keys("Super+s"), lambda: s.keys("Escape"), "08c-module-control",
                       "Control Center")
    check_module_opens(s, "right", lambda: s.keys("Super+v"), lambda: s.keys("Escape"), "08d-module-notifications",
                       "Notifications")


def prepare(tmp):
    """A Downloads folder for the live updates to follow."""
    (tmp / "home" / "Downloads").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Downloads"\n', encoding="utf-8")


def click_rect(s, rect):
    x, y, w, h = rect
    s.click(x + w / 2, y + h / 2)


def open_widgets(s):
    lx, ly, lw, lh = s.debug(DOCK)["live"]["rect"]
    s.click(lx + 12, ly + lh / 2)
    return s.wait_for("widgets open", lambda: (l := live(s))["panelOpen"] and l["panel"]["timerButtons"]
                      and None not in l["panel"]["timerButtons"][0]["rect"] and l)


def check_smart_live(s):
    """More live activities, and how several share the area."""
    # The idle glance: notifications waiting (one from the earlier check).
    lv = s.wait_for("notifications waiting", lambda: (l := live(s))["kind"] == "idle" and l)
    s.check(f"with nothing going on, waiting notifications show ({lv['labels']})",
            any("notification" in t for t in lv["labels"]))

    # Caps Lock.
    s.keys("Caps_Lock")
    lv = s.wait_for("Caps Lock on", lambda: (l := live(s))["kind"] == "keyboard" and l)
    s.check(f"Caps Lock shows live ({lv['labels']})", "Caps Lock on" in lv["labels"])
    s.keys("Caps_Lock")
    s.wait_for("Caps Lock off", lambda: "Caps Lock off" in live(s)["labels"])
    s.check("and when it is turned off", True)

    # A download: while the browser writes it, then when it is done.
    downloads = s.tmp / "home" / "Downloads"
    partial = downloads / "jeronix.iso.part"
    partial.write_bytes(b"x" * 300000)
    lv = s.wait_for("download", lambda: (l := live(s)) and "download" in l["ongoing"] and l, timeout=10)
    s.wait_for("download shown", lambda: "jeronix.iso · 300 KB" in live(s)["labels"], timeout=10)
    s.check("a download in progress shows its name and size", True)
    partial.rename(downloads / "jeronix.iso")
    lv = s.wait_for("downloaded", lambda: (l := live(s))["kind"] == "downloaded" and l, timeout=10)
    s.check(f"a finished download shows for a moment ({lv['labels']})",
            "Downloaded" in lv["labels"] and "jeronix.iso" in lv["labels"] and "download" not in lv["ongoing"])

    # A timer, from the Timer widget (once the download glimpse, whose click
    # would open the file, has passed).
    s.wait_for("download glimpse over", lambda: live(s)["kind"] != "downloaded", timeout=10)
    panel = open_widgets(s)["panel"]
    one = next(b for b in panel["timerButtons"] if b["name"] == "Timer 1 min")
    click_rect(s, one["rect"])
    lv = s.wait_for("timer", lambda: (l := live(s)) and any(i.startswith("timer-") for i in l["ongoing"]) and l)
    timer = next(i for i in lv["ongoing"] if i.startswith("timer-"))
    rows = s.wait_for("timer row", lambda: timer in live(s)["panel"]["activities"] and live(s)["panel"])
    s.check(f"the Timer widget starts a timer, listed under Activities ({rows['activities']})", True)
    s.keys("Escape")
    s.wait_for("widgets closed", lambda: not live(s)["panelOpen"])
    lv = s.wait_for("timer shown", lambda: (l := live(s))["kind"] == "timer" and l)
    s.check(f"the timer counts down in the taskbar ({lv['labels']})",
            any(t in lv["labels"] for t in ("1:00", "0:59", "0:58")) and
            [b["name"] for b in lv["buttons"]] == ["Pause", "Stop"])
    time.sleep(2)
    later = live(s)
    s.check(f"it ticks, updating in place ({later['labels']})",
            any(t in later["labels"] for t in ("0:57", "0:58", "0:59")) and later["labels"] != lv["labels"])

    # The island: a timer takes its color, and hovering expands it with more.
    s.check(f"a timer is orange with dynamic colors ({later['tint']})", later["tint"] == [245, 128, 20])
    mx, my, mw, mh = s.debug(DOCK)["monitor"]
    x, y, w, h = later["rect"]
    s.pointer(x + 20, y + h / 2)
    lv = s.wait_for("expanded", lambda: (l := live(s))["expanded"] and None not in l["buttons"][-1]["rect"] and l)
    names = [b["name"] for b in lv["buttons"]]
    s.check(f"hovering expands it with more controls, the first ones in place ({names})",
            names == ["Pause", "Stop", "Add a minute"])
    lv = s.wait_for("grown", lambda: (l := live(s))["rect"][2] > w and l)
    s.check(f"expanding grows the area ({w} -> {lv['rect'][2]})", True)
    time.sleep(0.5)
    s.screenshot("08c-live-expanded")
    click_rect(s, lv["buttons"][-1]["rect"])
    lv = s.wait_for("a minute more", lambda: any(t.startswith("1:5") for t in live(s)["labels"]) and live(s))
    s.check(f"'Add a minute' adds a minute ({lv['labels']})", True)
    s.pointer(mx + mw / 2, my + mh / 3)
    s.wait_for("collapsed", lambda: not live(s)["expanded"])
    s.check("leaving brings it back to its compact size", [b["name"] for b in live(s)["buttons"]] == ["Pause", "Stop"])

    # Several going on: a count, and scrolling goes through them.
    player = FakePlayer(s)
    try:
        lv = s.wait_for("music too", lambda: pumped(s, lambda: (l := live(s))["more"] == 1 and l))
        s.check(f"with music too, the timer shows with +1 ({lv['labels']})",
                lv["kind"] == "timer" and "+1" in lv["labels"])
        s.screenshot("09a-live-timer-and-more")
        x, y, w, h = lv["rect"]
        s.probe("Scroll", (float(x + 20), float(y + h / 2), "down"), "(dds)")
        lv = s.wait_for("scrolled", lambda: pumped(s, lambda: (l := live(s))["kind"] == "media" and l))
        s.check(f"scrolling shows the next one, the music ({lv['labels']})",
                "Test Song" in lv["labels"] and lv["pinned"] == "media" and "+1" in lv["labels"])
        s.probe("Scroll", (float(x + 20), float(y + h / 2), "up"), "(dds)")
        s.wait_for("scrolled back", lambda: pumped(s, lambda: live(s)["kind"] == "timer"))
        s.check("and back", True)

        # Pause and stop from the Activities card.
        open_widgets(s)
        buttons = s.wait_for("timer buttons", lambda: (b := live(s)["panel"]["activityButtons"].get(timer))
                             and None not in b[0]["rect"] and b)
        click_rect(s, next(b for b in buttons if b["name"] == "Pause")["rect"])
        s.wait_for("paused", lambda: [b["name"] for b in live(s)["panel"]["activityButtons"][timer]]
                   == ["Resume", "Stop", "Add a minute"])
        s.check("Pause in the Activities card pauses the timer", True)
        s.screenshot("09b-widgets-activities")
        buttons = s.wait_for("resume button", lambda: (b := live(s)["panel"]["activityButtons"][timer])
                             and None not in b[0]["rect"] and b)
        click_rect(s, next(b for b in buttons if b["name"] == "Stop")["rect"])
        s.wait_for("stopped", lambda: timer not in live(s)["ongoing"])
        s.check("Stop ends it", True)

        # A focus session turns on Do Not Disturb, and gives it back.
        panel = live(s)["panel"]
        focus = next(b for b in panel["timerButtons"] if b["name"].startswith("Focus"))
        click_rect(s, focus["rect"])
        banners = lambda: s.probe("GetSetting", ("org.gnome.desktop.notifications", "show-banners"), "(ss)")[0]
        s.wait_for("Do Not Disturb", lambda: banners() == "false")
        s.check("a focus session turns on Do Not Disturb", True)
        session = next(i for i in live(s)["ongoing"] if i.startswith("timer-"))
        buttons = s.wait_for("focus row", lambda: (b := live(s)["panel"]["activityButtons"].get(session))
                             and None not in b[0]["rect"] and b)
        click_rect(s, next(b for b in buttons if b["name"] == "Stop")["rect"])
        s.wait_for("Do Not Disturb off", lambda: banners() == "true")
        s.check("stopping it turns Do Not Disturb off again", True)
        s.check("the notifications waiting are listed with the activities",
                live(s)["panel"]["notificationsWaiting"])
        s.keys("Escape")
        s.wait_for("widgets closed", lambda: not live(s)["panelOpen"])
    finally:
        player.close()
    s.wait_for("music gone", lambda: pumped(s, lambda: "media" not in live(s)["ongoing"]))

    # Each kind can be turned off in Settings.
    s.set_ext(DOCK, "live-activities", "['media', 'timers']")
    time.sleep(0.5)
    s.keys("Caps_Lock")
    time.sleep(1)
    s.check("an activity turned off in Settings does not show", live(s)["kind"] != "keyboard")
    s.keys("Caps_Lock")
    s.set_ext(DOCK, "live-activities", "['media', 'timers', 'recording', 'privacy', 'downloads', 'levels', "
                                       "'notifications', 'battery', 'network', 'keyboard', 'stay-awake']")


def run(s):
    s.start()
    print(f"# session mode: {s.mode}")
    s.pointer(800, 500)  # the virtual pointer starts in the hot corner
    for uuid in (THEME, QS, PANEL, DOCK):
        s.enable(uuid)
    s.check("the taskbar stays visible by default (Windows 11)", s.debug(DOCK)["behavior"] == "always")
    # Wi-Fi beside the network icon whenever there is an adapter (this
    # machine's own, through the system bus), never a second icon for it.
    wifi = s.wait_for("Wi-Fi indicator", lambda: (q := s.debug(QS)) and q["wifi"] and q["wifi"], timeout=10)
    if wifi["device"]:
        s.check(f"Wi-Fi adapter {wifi['device']}: its icon shows ({wifi['icon']})",
                wifi["visible"] and wifi["icon"].startswith("network-wireless-"))
    else:
        s.check("no Wi-Fi adapter: no Wi-Fi icon", not wifi["visible"])
    s.set_ext(DOCK, "behavior", "'intellihide'")  # the hiding checks below

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
    s.check("the default is the Windows 11 taskbar as expandable modules, across the screen",
            dock["style"] == "modules" and x == mx and w == mw)
    state = s.state()
    s.check(f"Quick Settings and the clock/notification center are in the taskbar tray ({dock['tray']})",
            dock["tray"] == ["quickSettings", "dateMenu"]
            and state["quickSettingsParent"] == "jeronix-tray" and state["dateMenuParent"] == "jeronix-tray")
    s.check("GNOME's top bar is hidden while the taskbar carries the tray",
            dock["topBarHidden"] and state["panelVisible"] is False)
    cc = dock["controlCenter"]
    s.check(f"the Control Center replaces the Quick Settings grid ({cc and cc['modules']})",
            cc and cc["parentIsQuickSettings"] and cc["gnomeVisible"] == 0 and cc["modules"])
    s.keys("Super+s")
    cc = s.wait_for("Control Center open", lambda: (c := s.debug(DOCK)["controlCenter"])["open"] and c)
    s.check("Super+S opens the Control Center and GNOME's grid stays hidden", cc["gnomeVisible"] == 0)
    s.screenshot("01d-control-center")
    s.keys("Escape")
    s.wait_for("Control Center closed", lambda: not s.debug(DOCK)["controlCenter"]["open"])
    s.set_ext(DOCK, "control-center-modules", "['focus', 'dark-mode', 'sound']")
    cc = s.wait_for("fewer modules", lambda: (c := s.debug(DOCK)["controlCenter"])
                    and "connectivity(wifi)" not in c["modules"] and c)
    s.check(f"choosing modules changes the Control Center live ({cc['modules']})",
            all(m in ("focus", "dark-mode", "sound") for m in cc["modules"]) and "focus" in cc["modules"])
    s.set_ext(DOCK, "control-center-reduce-transparency", "true")
    s.wait_for("solid background", lambda: s.debug(DOCK)["controlCenter"]["solid"])
    s.check("Reduce transparency applies live", True)
    s.set_ext(DOCK, "control-center-reduce-transparency", "false")
    s.set_ext(DOCK, "control-center-modules", repr(CC_DEFAULT))
    check_live_updates(s, mx, mw)
    check_smart_live(s)
    check_modules(s, mx, mw)

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
    s.check(f"the Start menu shows its own pinned apps ({start['startMenu']['pinned']})",
            start["startMenuTitle"] == "Pinned" and start["startMenu"]["pinned"]
            and start["startMenuApps"] == start["startMenu"]["pinned"])
    sx, sy, sw, sh = start["startMenu"]["rect"]
    s.check(f"the Start menu is centered on the screen ({start['startMenu']['rect']})",
            abs((sx + sw / 2) - (mx + mw / 2)) <= 2)
    center_top = start["modules"]["rects"]["center"][1]
    s.check(f"the Start menu stands on the center module (bottom {sy + sh}, module top {center_top})",
            abs((sy + sh) - center_top) <= 1)
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

    # Start keeps its own pins (start-pinned-apps), apart from the taskbar's.
    pins = ["org.gnome.TextEditor.desktop", "missing.desktop", "org.gnome.Nautilus.desktop"]
    s.set_ext(DOCK, "start-pinned-apps", repr(pins))
    s.keys("Super")
    start = s.wait_for("Start menu with new pins", lambda: (d := s.debug(DOCK))["startMenuOpen"]
                       and d["startMenu"]["pinned"] == [pins[0], pins[2]] and d)
    s.check("Start shows its pins in order and skips apps that are not installed",
            start["startMenuApps"] == [pins[0], pins[2]])
    s.check("changing the Start pins leaves the taskbar's pins alone", start["favorites"] == FAVORITES)
    s.keys("Escape")
    s.wait_for("Start menu closed", lambda: not s.debug(DOCK)["startMenuOpen"])

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
    shown = s.wait_for("one module", lambda: (m := s.debug(DOCK)["modulesShown"]) == ["center"] and m, timeout=10)
    s.check(f"only the module above the pointer comes back ({shown})", shown == ["center"])
    s.pointer(mx + mw - 1, my + mh - 1)
    shown = s.wait_for("right module alone", lambda: (m := s.debug(DOCK)["modulesShown"]) == ["right"] and m,
                       timeout=10)
    s.check(f"moving along the edge swaps to the module above the pointer ({shown})", shown == ["right"])
    s.screenshot("03b-one-module")
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

    # -- lock screen: JERONIX look, and everything back after unlocking ----------
    s.probe("Lock")
    locked = s.wait_for("lock screen", lambda: (st := s.state())["locked"] and st["sessionMode"] == "unlock-dialog"
                        and st)
    # Locking blanks the screen until there is activity, as on a real machine.
    for x in (700, 760, 820):
        s.pointer(x, 500)
    time.sleep(2)
    s.screenshot("05-lock-screen")
    lock = s.wait_for("JERONIX lock screen", lambda: (d := s.debug(THEME)) and d["adopted"] and d)
    s.check(f"the JERONIX lock screen replaces GNOME's ({lock})",
            lock["gnomeClockShown"] is False and lock["notificationsShown"] is False
            and lock["view"]["time"] and lock["view"]["opacity"] == 255 and lock["panelOpacity"] == 0)
    s.keys("Return")  # reveals the password prompt
    time.sleep(2)
    s.screenshot("05b-lock-prompt")
    prompt = s.debug(THEME)
    s.check("the password prompt fades the JERONIX clock out and brings the top bar back",
            prompt["view"]["opacity"] == 0 and prompt["panelOpacity"] == 255)
    s.check("the JERONIX theme stays on the lock screen", locked["extensionStates"].get(THEME) == 1)
    s.check("the taskbar is not on the lock screen", locked["extensionStates"].get(DOCK) != 1)
    s.probe("Unlock")
    s.wait_for("unlocked", lambda: not s.state()["locked"])
    s.wait_for("lock screen released", lambda: not s.debug(THEME)["adopted"])
    s.check("after unlocking, the top bar is GNOME's again", s.debug(THEME)["panelOpacity"] == 255)
    dock = s.wait_for("taskbar back", lambda: (d := s.debug(DOCK)) and d["items"] and d)
    s.check("after unlocking, the taskbar and Control Center are back",
            dock["controlCenter"] and dock["controlCenter"]["gnomeVisible"] == 0)

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
        prefix="jeronix-desktop-", prepare=prepare))
