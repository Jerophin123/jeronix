# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure layout schema, validation and apply/restore round trip.

Anything that writes settings runs in a subprocess with a temporary HOME,
the keyfile GSettings backend and no session bus, so the user's dconf
database is never touched.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_layout as layout_tool  # noqa: E402

PURE = ROOT / "desktop" / "layouts" / "pure.json"
TOOL = ROOT / "scripts" / "jeronix_layout.py"


def has_gsettings_schemas():
    try:
        from gi.repository import Gio
        return Gio.SettingsSchemaSource.get_default().lookup("org.gnome.desktop.interface", True) is not None
    except ImportError:
        return False


class Sandbox:
    """Temporary XDG tree plus an environment that isolates GSettings."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for sub in ("home", "data", "state", "config/glib-2.0/settings"):
            (self.root / sub).mkdir(parents=True)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(self.root / "home"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "GSETTINGS_BACKEND": "keyfile",
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
        }
        self.keyfile = self.root / "config" / "glib-2.0" / "settings" / "keyfile"

    def run(self, *args, check=True):
        result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], env=self.env,
                                capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise AssertionError(f"{args} failed:\n{result.stdout}{result.stderr}")
        return result

    def get(self, schema, key):
        code = ("import sys; from gi.repository import Gio; "
                "print(Gio.Settings.new(sys.argv[1]).get_value(sys.argv[2]).print_(False))")
        return subprocess.run([sys.executable, "-c", code, schema, key], env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def install_wallpapers(self):
        for asset in layout_tool.ASSETS.values():
            path = self.root / "data" / asset
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"placeholder")

    def close(self):
        self._tmp.cleanup()


class LayoutStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pure = json.loads(PURE.read_text(encoding="utf-8"))

    def test_pure_is_structurally_valid(self):
        self.assertEqual(layout_tool.check_structure(self.pure), [])

    def test_pure_targets_supported_shell(self):
        platform = json.loads((ROOT / "config" / "platform.json").read_text(encoding="utf-8"))
        self.assertEqual(self.pure["gnome_shell"], platform["gnome_shell"]["supported_versions"])

    def test_every_setting_explains_itself(self):
        for s in self.pure["settings"]:
            self.assertGreater(len(s["reason"]), 10, s["key"])

    def test_allowlist_excludes_anything_that_can_run_code_or_toggle_extensions(self):
        forbidden = {("org.gnome.shell", "enabled-extensions"), ("org.gnome.shell", "disabled-extensions"),
                     ("org.gnome.shell", "disable-user-extensions")}
        for schema, keys in layout_tool.ALLOWED.items():
            self.assertNotIn("keybinding", schema)
            self.assertNotIn("media-keys", schema)
            for key in keys:
                self.assertNotIn((schema, key), forbidden)
                self.assertNotRegex(key, r"command|exec|binding|autostart")

    def test_invalid_layouts_are_rejected(self):
        cases = {
            "unknown top-level field": lambda l: l.update(run="rm -rf ~"),
            "non-allowlisted key": lambda l: l["settings"].append(
                {"schema": "org.gnome.shell", "key": "enabled-extensions", "value": [], "reason": "x"}),
            "custom keybinding": lambda l: l["settings"].append(
                {"schema": "org.gnome.settings-daemon.plugins.media-keys", "key": "custom-keybindings",
                 "value": [], "reason": "x"}),
            "unknown setting field": lambda l: l["settings"][0].update(command="true"),
            "duplicate": lambda l: l["settings"].append(copy.deepcopy(l["settings"][0])),
            "unknown asset": lambda l: l["settings"][9].update(value={"asset": "../../etc/passwd"}),
            "unsupported shell": lambda l: l.update(gnome_shell=["49"]),
            "bad version": lambda l: l.update(version="1"),
            "wrong schema version": lambda l: l.update(schema=2),
            "object value": lambda l: l["settings"][0].update(value={"x": 1}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                broken = copy.deepcopy(self.pure)
                mutate(broken)
                self.assertTrue(layout_tool.check_structure(broken))


@unittest.skipUnless(has_gsettings_schemas(), "GNOME GSettings schemas not installed")
class LayoutGSettingsTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()

    def tearDown(self):
        self.box.close()

    def write_layout(self, mutate):
        pure = json.loads(PURE.read_text(encoding="utf-8"))
        mutate(pure)
        path = self.box.root / "layout.json"
        path.write_text(json.dumps(pure), encoding="utf-8")
        return path

    def test_pure_validates_against_installed_schemas(self):
        result = self.box.run("validate", PURE)
        self.assertIn("valid", result.stdout)

    def test_type_and_range_errors_are_caught_before_writing(self):
        cases = {
            "string for bool": lambda l: l["settings"][2].update(value="yes"),
            "enum out of range": lambda l: l["settings"][0].update(value="prefer-purple"),
            "missing required schema": lambda l: l["settings"].append(
                {"schema": "org.gnome.desktop.interface", "key": "no-such-key", "value": 1, "reason": "x"}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                path = self.write_layout(mutate)
                self.assertEqual(self.box.run("validate", path, check=False).returncode, 1)
                self.assertEqual(self.box.run("apply", path, check=False).returncode, 1)
                self.assertFalse(self.box.keyfile.exists() and "prefer-" in self.box.keyfile.read_text(),
                                 "nothing may be written when validation fails")

    def test_apply_requires_installed_assets(self):
        result = self.box.run("apply", PURE, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("install-desktop-dev.sh", result.stderr)
        self.assertFalse(list((self.box.root / "state").rglob("*.json")), "no snapshot without apply")

    def test_plan_changes_nothing(self):
        self.box.run("plan", PURE)
        self.assertFalse(self.box.keyfile.exists() and self.box.keyfile.read_text().strip())

    def test_apply_then_restore_round_trip(self):
        self.box.install_wallpapers()
        # A value the user customized must come back exactly; untouched keys
        # must go back to their defaults rather than being pinned.
        self.box.keyfile.write_text("[org/gnome/desktop/interface]\nclock-show-weekday=false\n"
                                    "accent-color='teal'\n", encoding="utf-8")
        before = {k: self.box.get("org.gnome.desktop.interface", k) for k in ("color-scheme", "accent-color")}

        self.box.run("apply", PURE)
        self.assertEqual(self.box.get("org.gnome.desktop.interface", "color-scheme"), "'prefer-dark'")
        self.assertEqual(self.box.get("org.gnome.desktop.interface", "accent-color"), "'slate'")
        self.assertEqual(self.box.get("org.gnome.mutter", "dynamic-workspaces"), "true")
        wallpaper = (self.box.root / "data" / layout_tool.ASSETS["wallpaper-dark"]).as_uri()
        self.assertEqual(self.box.get("org.gnome.desktop.background", "picture-uri-dark"), f"'{wallpaper}'")
        snapshots = list((self.box.root / "state" / "jeronix" / "layout-snapshots").glob("*-pure.json"))
        self.assertEqual(len(snapshots), 1)

        self.box.run("restore")
        self.assertEqual(self.box.get("org.gnome.desktop.interface", "accent-color"), before["accent-color"])
        self.assertEqual(self.box.get("org.gnome.desktop.interface", "color-scheme"), before["color-scheme"])
        self.assertEqual(self.box.get("org.gnome.desktop.interface", "clock-show-weekday"), "false")
        text = self.box.keyfile.read_text(encoding="utf-8")
        self.assertNotIn("color-scheme", text, "default-valued keys are reset, not written")
        self.assertNotIn("dynamic-workspaces", text)

    def test_tampered_snapshot_is_refused(self):
        snap_dir = self.box.root / "state" / "jeronix" / "layout-snapshots"
        snap_dir.mkdir(parents=True)
        (snap_dir / "x.json").write_text(json.dumps({"schema": 1, "entries": [
            {"schema": "org.gnome.shell", "key": "enabled-extensions", "user_value": "@as []"}]}))
        result = self.box.run("restore", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not an allowed layout setting", result.stderr)


if __name__ == "__main__":
    unittest.main()
