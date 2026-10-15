#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the generated JERONIX shell theme inside a real, isolated, headless
GNOME Shell.

The shell runs in the same session mode as the desktop (ubuntu, so the Yaru
theme is underneath) with Ubuntu's mode extensions disabled. The test:

1. enables jeronix-shell-theme and checks that GNOME Shell loaded the dark
   stylesheet without errors;
2. resolves real computed styles (panel, popovers, Quick Settings, search,
   notifications, focus rings) and compares them with the design tokens;
3. switches the color scheme and repeats the checks for the light variant;
4. disables the extension and checks that the default look is restored.

Isolation is the same as extension_lifecycle.py: temporary HOME/XDG tree,
private D-Bus session bus and a keyfile GSettings backend inside the
temporary tree. The user's desktop and dconf database are not touched.

Usage: python3 tests/integration/theme_lifecycle.py [--keep-logs]
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_design as design  # noqa: E402

PROBE_SRC = Path(__file__).resolve().parent / "probe-extension"
PROBE_UUID = "jeronix-test-probe@jeronix"
UUID = design.THEME_UUID
MODES_DIR = Path("/usr/share/gnome-shell/modes")

STATE_ACTIVE = 1
STATE_INACTIVE = 2
STATE_ERROR = 3


def session_mode():
    """The distribution's session mode if it has one, else upstream 'user'."""
    ubuntu = MODES_DIR / "ubuntu.json"
    if ubuntu.exists():
        return "ubuntu", json.loads(ubuntu.read_text(encoding="utf-8")).get("enabledExtensions", [])
    return "user", []


def gvariant_strv(items):
    return "[" + ", ".join(f"'{i}'" for i in items) + "]"


def remove_sandbox(tmp):
    """Deletes the sandbox. Session helpers such as gvfsd can recreate
    run/ for a moment after the bus closes, so retry briefly."""
    for _ in range(10):
        shutil.rmtree(tmp, ignore_errors=True)
        if not tmp.exists():
            return
        time.sleep(0.3)


def outer(keep_logs):
    for tool in ("gnome-shell", "dbus-run-session"):
        if not shutil.which(tool):
            print(f"SKIP: {tool} not installed")
            return 77
    tmp = Path(tempfile.mkdtemp(prefix="jeronix-theme-"))
    try:
        for sub in ("home", "data", "config/glib-2.0/settings", "cache", "run"):
            (tmp / sub).mkdir(parents=True)
        (tmp / "run").chmod(0o700)
        design.build(tmp / "build", parts=("extensions",))
        ext_dir = tmp / "data" / "gnome-shell" / "extensions"
        shutil.copytree(tmp / "build" / "extensions" / UUID, ext_dir / UUID)
        shutil.copytree(PROBE_SRC, ext_dir / PROBE_UUID)

        mode, mode_extensions = session_mode()
        # Mode extensions (dock, desktop icons, ...) would add noise and
        # their own CSS; keep them loaded but disabled.
        (tmp / "config" / "glib-2.0" / "settings" / "keyfile").write_text(
            "[org/gnome/shell]\n"
            f"disabled-extensions={gvariant_strv(mode_extensions)}\n"
            "[org/gnome/desktop/interface]\n"
            "color-scheme='prefer-dark'\n", encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(tmp / "home"),
            "XDG_DATA_HOME": str(tmp / "data"),
            "XDG_CONFIG_HOME": str(tmp / "config"),
            "XDG_CACHE_HOME": str(tmp / "cache"),
            "XDG_RUNTIME_DIR": str(tmp / "run"),
            "GSETTINGS_BACKEND": "keyfile",
            "JERONIX_TEST_TMP": str(tmp),
            "JERONIX_TEST_MODE": mode,
        }
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
            remove_sandbox(tmp)


class Inner:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.tmp = Path(os.environ["JERONIX_TEST_TMP"])
        self.mode = os.environ["JERONIX_TEST_MODE"]
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.tokens = design.load_tokens()
        self.proc = None
        self.passed = 0

    def call(self, name, path, iface, method, args=None, sig=None):
        params = self.GLib.Variant(sig, args) if sig else None
        reply = self.bus.call_sync(name, path, iface, method, params, None,
                                   self.Gio.DBusCallFlags.NONE, 10000, None)
        return reply.unpack() if reply else ()

    def probe(self, method, args=None, sig=None):
        return self.call("org.jeronix.Test.Probe", "/org/jeronix/Test/Probe",
                         "org.jeronix.Test.Probe", method, args, sig)

    def shell_ext(self, method, uuid):
        return self.call("org.gnome.Shell", "/org/gnome/Shell",
                         "org.gnome.Shell.Extensions", method, (uuid,), "(s)")

    def ext_state(self, uuid):
        info = self.shell_ext("GetExtensionInfo", uuid)[0]
        return int(info.get("state", 0)), info.get("error", "")

    def has_name(self, name):
        return self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                         "org.freedesktop.DBus", "NameHasOwner", (name,), "(s)")[0]

    def style(self, chain, prop):
        return self.probe("StyleColor", (json.dumps(chain), prop), "(ss)")[0]

    def our_stylesheets(self):
        return [Path(p).name for p in self.probe("CustomStylesheets")[0] if f"/{UUID}/" in p]

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

    def start(self):
        log = open(self.tmp / "shell.log", "w")
        self.proc = subprocess.Popen(
            ["gnome-shell", "--headless", "--wayland", "--no-x11", f"--mode={self.mode}",
             "--virtual-monitor", "1280x800", "--wayland-display", "jeronix-theme-0"],
            stdout=log, stderr=subprocess.STDOUT)
        self.wait_for("org.gnome.Shell on the bus", lambda: self.has_name("org.gnome.Shell"))
        self.wait_for("extension manager", lambda: self.ext_state(UUID)[0] != 0)
        self.shell_ext("EnableExtension", PROBE_UUID)
        self.wait_for("test probe", lambda: self.has_name("org.jeronix.Test.Probe"))

    def compare_with_tokens(self, variant):
        mismatches = []
        for c in design.theme_checks(self.tokens, variant):
            expected = c["expect"].lower() + "ff"
            actual = self.style(c["chain"], c["property"])
            if actual != expected:
                mismatches.append(f"{c['what']}: {c['property']} is {actual or 'unset'}, token {expected}")
        for m in mismatches:
            print(f"  mismatch [{variant}] {m}")
        count = len(design.theme_checks(self.tokens, variant))
        self.check(f"[{variant}] {count} computed styles match the design tokens", not mismatches)

    def run(self):
        self.start()
        print(f"# session mode: {self.mode}")
        panel = [{"name": "panel"}]
        baseline = self.style(panel, "background-color")
        self.check(f"default theme panel color differs from JERONIX ({baseline})",
                   baseline != self.tokens["color"]["dark"]["panel"].lower() + "ff")

        self.shell_ext("EnableExtension", UUID)
        state, error = self.wait_for("extension settled",
                                     lambda: (s := self.ext_state(UUID))[0] in (STATE_ACTIVE, STATE_ERROR) and s)
        self.check(f"theme enabled without error (state={state}, error={error!r})",
                   state == STATE_ACTIVE and not error)
        self.check("dark stylesheet loaded", self.our_stylesheets() == ["stylesheet-dark.css"])
        self.compare_with_tokens("dark")

        self.probe("SetColorScheme", ("prefer-light",), "(s)")
        self.wait_for("light stylesheet", lambda: self.our_stylesheets() == ["stylesheet-light.css"])
        self.check("switching to light swaps in the light stylesheet", True)
        self.compare_with_tokens("light")

        self.probe("SetColorScheme", ("prefer-dark",), "(s)")
        self.wait_for("dark stylesheet again", lambda: self.our_stylesheets() == ["stylesheet-dark.css"])
        self.shell_ext("DisableExtension", UUID)
        self.wait_for("extension inactive", lambda: self.ext_state(UUID)[0] == STATE_INACTIVE)
        self.check("disable unloads every JERONIX stylesheet", self.our_stylesheets() == [])
        self.check("disable restores the default panel color",
                   self.style(panel, "background-color") == baseline)

        log = (self.tmp / "shell.log").read_text(errors="replace")
        bad = [line for line in log.splitlines() if UUID in line]
        for line in bad:
            print(f"  log: {line}")
        self.check("no CSS or JS errors mention the theme in the shell log", not bad)
        print(f"1..{self.passed}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


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
