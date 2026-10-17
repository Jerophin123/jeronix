# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable isolated headless GNOME Shell for integration tests.

The test script calls run_isolated(); it prepares a temporary HOME/XDG tree
(keyfile GSettings, all JERONIX extensions built from source plus the test
probe) and re-executes the script on a private D-Bus session bus, where
Session drives a real `gnome-shell --headless` in the distribution's
session mode. The user's desktop and dconf are never touched.
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

HERE = Path(__file__).resolve().parent
PROBE_UUID = "jeronix-test-probe@jeronix"
MODES_DIR = Path("/usr/share/gnome-shell/modes")
STATE_ACTIVE, STATE_INACTIVE, STATE_ERROR = 1, 2, 3


def session_mode():
    ubuntu = MODES_DIR / "ubuntu.json"
    if ubuntu.exists():
        return "ubuntu", json.loads(ubuntu.read_text(encoding="utf-8")).get("enabledExtensions", [])
    return "user", []


def strv(items):
    return "[" + ", ".join(f"'{i}'" for i in items) + "]"


def remove_tree(path):
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.3)


def run_isolated(script, keyfile_extra="", desktop_files=(), keep_logs=False, prefix="jeronix-shell-", prepare=None,
                 keep_mode_extensions=()):
    """Outer half: sandbox setup, then `script --inner` on a private bus."""
    for tool in ("gnome-shell", "dbus-run-session", "glib-compile-schemas"):
        if not shutil.which(tool):
            print(f"SKIP: {tool} not installed")
            return 77
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        for sub in ("home", "data/applications", "config/glib-2.0/settings", "cache", "run", "shots"):
            (tmp / sub).mkdir(parents=True)
        (tmp / "run").chmod(0o700)
        design.build(tmp / "build", parts=("extensions",))
        ext_dir = tmp / "data" / "gnome-shell" / "extensions"
        shutil.copytree(tmp / "build" / "extensions", ext_dir)
        shutil.copytree(HERE / "probe-extension", ext_dir / PROBE_UUID)
        if prepare:
            prepare(tmp)
        for name, text in desktop_files:
            (tmp / "data" / "applications" / name).write_text(text, encoding="utf-8")
        mode, mode_extensions = session_mode()
        (tmp / "config" / "glib-2.0" / "settings" / "keyfile").write_text(
            "[org/gnome/shell]\n"
            f"disabled-extensions={strv([e for e in mode_extensions if e not in keep_mode_extensions])}\n"
            f"{keyfile_extra}\n", encoding="utf-8")
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
            "JERONIX_SHOTS": os.environ.get("JERONIX_SHOTS", ""),
        }
        with open(tmp / "bus.log", "w") as bus_log:
            result = subprocess.run(["dbus-run-session", "--", sys.executable, str(script), "--inner"],
                                    env=env, stderr=bus_log, timeout=600)
        if result.returncode != 0 or keep_logs:
            for name in ("bus.log", "shell.log", "client.log"):
                log = tmp / name
                if log.exists():
                    print(f"---- {name} (tail) ----")
                    print("\n".join(log.read_text(errors="replace").splitlines()[-40:]))
        return result.returncode
    finally:
        if keep_logs:
            print(f"logs kept in {tmp}")
        else:
            remove_tree(tmp)


class Session:
    """Inner half: drives the headless shell over the private bus."""

    display = "jeronix-test-1"

    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.tmp = Path(os.environ["JERONIX_TEST_TMP"])
        self.mode = os.environ["JERONIX_TEST_MODE"]
        self.shots = Path(os.environ["JERONIX_SHOTS"]) if os.environ.get("JERONIX_SHOTS") else None
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.procs = []
        self.passed = 0

    # -- D-Bus ---------------------------------------------------------
    def call(self, name, path, iface, method, args=None, sig=None):
        params = self.GLib.Variant(sig, args) if sig else None
        reply = self.bus.call_sync(name, path, iface, method, params, None,
                                   self.Gio.DBusCallFlags.NONE, 10000, None)
        return reply.unpack() if reply else ()

    def probe(self, method, args=None, sig=None):
        return self.call("org.jeronix.Test.Probe", "/org/jeronix/Test/Probe",
                         "org.jeronix.Test.Probe", method, args, sig)

    def shell_ext(self, method, uuid):
        return self.call("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions",
                         method, (uuid,), "(s)")

    def ext_state(self, uuid):
        info = self.shell_ext("GetExtensionInfo", uuid)[0]
        return int(info.get("state", 0)), info.get("error", "")

    def has_name(self, name):
        return self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                         "NameHasOwner", (name,), "(s)")[0]

    def debug(self, uuid):
        return json.loads(self.probe("ExtensionDebug", (uuid,), "(s)")[0])

    def state(self):
        return json.loads(self.probe("State")[0])

    def set_ext(self, uuid, key, value):
        self.probe("SetExtensionSetting", (uuid, key, value), "(sss)")

    def pointer(self, x, y):
        self.probe("MovePointer", (float(x), float(y)), "(dd)")

    def window(self, title, action):
        return self.probe("WindowAction", (title, action), "(ss)")[0]

    def click(self, x, y):
        self.probe("Click", (float(x), float(y)), "(dd)")

    def set_setting(self, schema, key, value):
        self.probe("SetSetting", (schema, key, value), "(sss)")

    def keys(self, combo):
        """Presses a combination such as 'Super+j' on a virtual keyboard."""
        self.probe("PressKeys", (combo,), "(s)")

    def sandbox_env(self):
        """Environment for helper processes that share the shell's settings."""
        return dict(os.environ)

    # -- helpers -------------------------------------------------------
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

    def enable(self, uuid):
        self.shell_ext("EnableExtension", uuid)
        state, error = self.wait_for(f"{uuid} settled",
                                     lambda: (s := self.ext_state(uuid))[0] in (STATE_ACTIVE, STATE_ERROR) and s)
        self.check(f"{uuid} enabled without error ({error!r})", state == STATE_ACTIVE and not error)

    def disable(self, uuid):
        self.shell_ext("DisableExtension", uuid)
        self.wait_for(f"{uuid} inactive", lambda: self.ext_state(uuid)[0] == STATE_INACTIVE)
        self.check(f"{uuid} disabled cleanly", self.ext_state(uuid)[1] == "")

    def screenshot(self, name):
        """Saves a PNG of the shell into $JERONIX_SHOTS, if set."""
        if not self.shots:
            return None
        self.shots.mkdir(parents=True, exist_ok=True)
        path = self.shots / f"{name}.png"
        path.unlink(missing_ok=True)
        time.sleep(0.6)  # let animations settle
        self.probe("Screenshot", (str(path),), "(s)")
        self.wait_for(f"screenshot {name}", lambda: path.exists() and path.stat().st_size > 1000)
        time.sleep(0.2)
        return path

    def start(self, size="1600x1000"):
        log = open(self.tmp / "shell.log", "w")
        self.procs.append(subprocess.Popen(
            ["gnome-shell", "--headless", "--wayland", "--no-x11", f"--mode={self.mode}",
             "--virtual-monitor", size, "--wayland-display", self.display],
            stdout=log, stderr=subprocess.STDOUT))
        self.wait_for("org.gnome.Shell on the bus", lambda: self.has_name("org.gnome.Shell"))
        self.wait_for("extension manager", lambda: self.ext_state(PROBE_UUID)[0] != 0)
        self.shell_ext("EnableExtension", PROBE_UUID)
        self.wait_for("test probe", lambda: self.has_name("org.jeronix.Test.Probe"))
        # The shell starts in the overview; leave it so the desktop is shown.
        self.overview(False)

    def overview(self, visible):
        self.probe("SetOverview", (visible,), "(b)")
        self.wait_for(f"overview {'shown' if visible else 'hidden'}",
                      lambda: self.state()["overview"] == visible)
        time.sleep(0.5)  # animation

    def spawn_client(self, argv, env_extra=None):
        """Starts an application on the headless shell's Wayland display."""
        env = dict(os.environ, WAYLAND_DISPLAY=self.display, GDK_BACKEND="wayland", **(env_extra or {}))
        env.pop("DISPLAY", None)
        log = open(self.tmp / "client.log", "a")
        proc = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(proc)
        return proc

    def stop(self):
        for proc in reversed(self.procs):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def shell_log_errors(self, needles):
        log = (self.tmp / "shell.log").read_text(errors="replace")
        return [line for line in log.splitlines() if any(n in line for n in needles)]


def main(run, script, **outer_kwargs):
    """Entry point: run(session) performs the checks."""
    if "--inner" in sys.argv:
        session = Session()
        try:
            run(session)
            print(f"1..{session.passed}")
            return 0
        except AssertionError as e:
            print(f"FAIL - {e}")
            return 1
        finally:
            session.stop()
    return run_isolated(script, keep_logs="--keep-logs" in sys.argv, **outer_kwargs)
