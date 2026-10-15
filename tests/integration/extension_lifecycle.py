#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Enable/disable lifecycle test for jeronix-quick-settings in a real,
isolated, headless GNOME Shell.

Isolation: a temporary HOME/XDG tree, a private D-Bus session bus
(dbus-run-session), in-memory GSettings and a private Wayland socket. The
user's running desktop, dconf database and installed extensions are not
touched.

Usage: python3 tests/integration/extension_lifecycle.py [--keep-logs]
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_SRC = ROOT / "desktop" / "extensions" / "jeronix-quick-settings"
PROBE_SRC = Path(__file__).resolve().parent / "probe-extension"
UUID = "jeronix-quick-settings@jeronix"
PROBE_UUID = "jeronix-test-probe@jeronix"
TOGGLE = "Stay Awake"
CYCLES = 3

# org.gnome.Shell.Extensions state values (js/misc/extensionUtils.js)
STATE_ACTIVE = 1
STATE_INACTIVE = 2
STATE_ERROR = 3
STATE_INITIALIZED = 6  # loaded, never enabled


def outer(keep_logs):
    """Prepare the sandbox and re-run this script on a private session bus."""
    for tool in ("gnome-shell", "dbus-run-session"):
        if not shutil.which(tool):
            print(f"SKIP: {tool} not installed")
            return 77
    tmp = Path(tempfile.mkdtemp(prefix="jeronix-lifecycle-"))
    try:
        for sub in ("home", "data", "config", "cache", "run"):
            (tmp / sub).mkdir()
        (tmp / "run").chmod(0o700)
        ext_dir = tmp / "data" / "gnome-shell" / "extensions"
        shutil.copytree(EXTENSION_SRC, ext_dir / UUID)
        shutil.copytree(PROBE_SRC, ext_dir / PROBE_UUID)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(tmp / "home"),
            "XDG_DATA_HOME": str(tmp / "data"),
            "XDG_CONFIG_HOME": str(tmp / "config"),
            "XDG_CACHE_HOME": str(tmp / "cache"),
            "XDG_RUNTIME_DIR": str(tmp / "run"),
            "GSETTINGS_BACKEND": "memory",
            "JERONIX_TEST_TMP": str(tmp),
        }
        # The private bus daemon is chatty; keep its output out of test results.
        with open(tmp / "bus.log", "w") as bus_log:
            result = subprocess.run(
                ["dbus-run-session", "--", sys.executable, __file__, "--inner"],
                env=env, stderr=bus_log, timeout=300)
        if result.returncode != 0 or keep_logs:
            for name in ("bus.log", "shell.log"):
                log = tmp / name
                if log.exists():
                    print(f"---- {name} (tail) ----")
                    print("\n".join(log.read_text(errors="replace").splitlines()[-40:]))
        return result.returncode
    finally:
        if keep_logs:
            print(f"logs kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


class Inner:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.tmp = Path(os.environ["JERONIX_TEST_TMP"])
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.procs = []
        self.passed = 0

    # -- D-Bus helpers -------------------------------------------------
    def call(self, name, path, iface, method, args=None, sig=None):
        params = self.GLib.Variant(sig, args) if sig else None
        reply = self.bus.call_sync(name, path, iface, method, params, None,
                                   self.Gio.DBusCallFlags.NONE, 10000, None)
        return reply.unpack() if reply else ()

    def shell_ext(self, method, uuid):
        return self.call("org.gnome.Shell", "/org/gnome/Shell",
                         "org.gnome.Shell.Extensions", method, (uuid,), "(s)")

    def ext_state(self, uuid):
        info = self.shell_ext("GetExtensionInfo", uuid)[0]
        return int(info.get("state", 0)), info.get("error", "")

    def toggles(self):
        return self.call("org.jeronix.Test.Probe", "/org/jeronix/Test/Probe",
                         "org.jeronix.Test.Probe", "FindToggles", (TOGGLE,), "(s)")

    def click(self):
        return self.call("org.jeronix.Test.Probe", "/org/jeronix/Test/Probe",
                         "org.jeronix.Test.Probe", "ClickToggle", (TOGGLE,), "(s)")[0]

    def held(self):
        return self.call("org.gnome.SessionManager", "/org/gnome/SessionManager",
                         "org.jeronix.Test.FakeSessionManager", "GetHeld")[0]

    def has_name(self, name):
        return self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                         "org.freedesktop.DBus", "NameHasOwner", (name,), "(s)")[0]

    # -- test helpers --------------------------------------------------
    def wait_for(self, what, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = predicate()
                if last:
                    return last
            except Exception as e:  # service may not be up yet
                last = e
            time.sleep(0.2)
        raise AssertionError(f"timed out waiting for {what} (last: {last!r})")

    def check(self, what, condition):
        if not condition:
            raise AssertionError(what)
        self.passed += 1
        print(f"ok - {what}")

    # -- lifecycle -----------------------------------------------------
    def start(self):
        fake = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_session_manager.py")],
                                stdout=subprocess.PIPE, text=True)
        self.procs.append(fake)
        self.fake = fake
        self.check("fake session manager ready", fake.stdout.readline().strip() == "READY")

        log = open(self.tmp / "shell.log", "w")
        shell = subprocess.Popen(
            ["gnome-shell", "--headless", "--wayland", "--no-x11",
             "--virtual-monitor", "1280x800", "--wayland-display", "jeronix-test-0"],
            stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(shell)
        self.wait_for("org.gnome.Shell on the bus", lambda: self.has_name("org.gnome.Shell"))
        self.wait_for("extension manager", lambda: self.ext_state(UUID)[0] != 0)

        self.shell_ext("EnableExtension", PROBE_UUID)
        self.wait_for("test probe", lambda: self.has_name("org.jeronix.Test.Probe"))

    def run(self):
        self.start()
        state, error = self.ext_state(UUID)
        self.check(f"extension discovered and not yet active (state={state})",
                   state in (STATE_INACTIVE, STATE_INITIALIZED) and not error)
        self.check("no toggle before enable", self.toggles()[0] == 0)

        for cycle in range(1, CYCLES + 1):
            self.shell_ext("EnableExtension", UUID)
            state, error = self.wait_for("extension active",
                                         lambda: (s := self.ext_state(UUID))[0] in (STATE_ACTIVE, STATE_ERROR) and s)
            self.check(f"[cycle {cycle}] enabled without error (state={state}, error={error!r})",
                       state == STATE_ACTIVE and not error)
            self.check(f"[cycle {cycle}] exactly one unchecked toggle", tuple(self.toggles()) == (1, False))

            self.check(f"[cycle {cycle}] toggle clicked", self.click())
            held = self.wait_for("inhibitor held", lambda: self.held())
            self.check(f"[cycle {cycle}] one idle|suspend inhibitor held by {UUID}",
                       len(held) == 1 and held[0][1] == UUID and held[0][2] == 12)
            self.wait_for("toggle checked", lambda: self.toggles()[1])
            self.check(f"[cycle {cycle}] toggle shows checked", True)

            if cycle == 1:
                # Turning it off through the UI releases the inhibitor ...
                self.click()
                self.wait_for("inhibitor released by click", lambda: not self.held())
                self.check(f"[cycle {cycle}] clicking again releases the inhibitor", True)
                self.wait_for("toggle unchecked", lambda: not self.toggles()[1])
                self.check(f"[cycle {cycle}] toggle shows unchecked", True)
                self.click()
                self.wait_for("inhibitor re-held", lambda: self.held())

            # ... and so does disabling the extension while it is on.
            self.shell_ext("DisableExtension", UUID)
            self.wait_for("extension inactive", lambda: self.ext_state(UUID)[0] == STATE_INACTIVE)
            self.check(f"[cycle {cycle}] disabled cleanly", self.ext_state(UUID)[1] == "")
            self.wait_for("inhibitor released on disable", lambda: not self.held())
            self.check(f"[cycle {cycle}] disable released the inhibitor", True)
            self.check(f"[cycle {cycle}] toggle removed on disable", self.toggles()[0] == 0)

        # Failure path: session manager unavailable.
        self.fake.terminate()
        self.fake.wait(5)
        self.wait_for("fake session manager gone", lambda: not self.has_name("org.gnome.SessionManager"))
        self.shell_ext("EnableExtension", UUID)
        self.wait_for("extension active", lambda: self.ext_state(UUID)[0] == STATE_ACTIVE)
        self.click()
        time.sleep(2)
        self.check("without a session manager the toggle stays unchecked", tuple(self.toggles()) == (1, False))
        self.check("extension still active after inhibit failure", self.ext_state(UUID)[0] == STATE_ACTIVE)
        self.shell_ext("DisableExtension", UUID)
        self.wait_for("extension inactive", lambda: self.ext_state(UUID)[0] == STATE_INACTIVE)

        log = (self.tmp / "shell.log").read_text(errors="replace")
        # Our source paths only show up in the log inside error stack traces.
        bad = [line for line in log.splitlines() if f"{UUID}/" in line]
        self.check("no JS errors attributed to the extension in the shell log", not bad)
        print(f"1..{self.passed}")

    def stop(self):
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def inner():
    test = Inner()
    try:
        test.run()
        return 0
    except AssertionError as e:
        print(f"FAIL - {e}")
        return 1
    finally:
        test.stop()


if __name__ == "__main__":
    if "--inner" in sys.argv:
        sys.exit(inner())
    sys.exit(outer("--keep-logs" in sys.argv))
