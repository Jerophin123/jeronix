# SPDX-License-Identifier: GPL-3.0-or-later
"""Layouts (Pure, Classic, Studio): schema, validation, extension switching
and apply/restore round trips.

Anything that writes settings runs in a subprocess with a temporary HOME,
the keyfile GSettings backend and no session bus, so the user's dconf
database is never touched. JERONIX extension schemas come from extensions
built into a temporary directory ($JERONIX_EXTENSION_DIRS).
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

LAYOUTS = ROOT / "desktop" / "layouts"
PURE = LAYOUTS / "pure.json"
ALL = [LAYOUTS / f"{name}.json" for name in ("pure", "classic", "studio")]
TOOL = ROOT / "scripts" / "jeronix_layout.py"
JERONIX_EXTENSIONS = {"jeronix-shell-theme@jeronix", "jeronix-panel@jeronix", "jeronix-dock@jeronix",
                      "jeronix-quick-settings@jeronix"}


def key(layout, name):
    """The setting with this key (layouts list each key once)."""
    return next(s for s in layout["settings"] if s["key"] == name)


def has_gsettings_schemas():
    try:
        from gi.repository import Gio
        return Gio.SettingsSchemaSource.get_default().lookup("org.gnome.desktop.interface", True) is not None
    except ImportError:
        return False


class Sandbox:
    """Temporary XDG tree plus an environment that isolates GSettings."""

    def __init__(self, extensions_dir):
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
            "JERONIX_EXTENSION_DIRS": str(extensions_dir),
        }
        self.keyfile = self.root / "config" / "glib-2.0" / "settings" / "keyfile"

    def run(self, *args, check=True):
        result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], env=self.env,
                                capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise AssertionError(f"{args} failed:\n{result.stdout}{result.stderr}")
        return result

    def get(self, schema, key):
        code = ("import sys; sys.path.insert(0, sys.argv[3]); import jeronix_layout as t; "
                "print(t.settings_for(sys.argv[1]).get_value(sys.argv[2]).print_(False))")
        return subprocess.run([sys.executable, "-c", code, schema, key, str(ROOT / "scripts")], env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def install_wallpapers(self):
        """Stand-ins for the installed assets: wallpapers and the icon theme."""
        for asset in layout_tool.ASSETS.values():
            path = self.root / "data" / asset
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"placeholder")
        theme = self.root / "data" / "icons" / "JERONIX"
        theme.mkdir(parents=True)
        (theme / "index.theme").write_text("[Icon Theme]\nName=JERONIX\n")

    def close(self):
        self._tmp.cleanup()


class LayoutStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layouts = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in ALL}
        cls.pure = cls.layouts["pure"]

    def test_all_layouts_are_structurally_valid(self):
        for name, layout in self.layouts.items():
            with self.subTest(layout=name):
                self.assertEqual(layout_tool.check_structure(layout), [])
                self.assertEqual(layout["id"], name)

    def test_layouts_target_supported_shell(self):
        platform = json.loads((ROOT / "config" / "platform.json").read_text(encoding="utf-8"))
        for layout in self.layouts.values():
            self.assertEqual(layout["gnome_shell"], platform["gnome_shell"]["supported_versions"])

    def test_every_setting_explains_itself(self):
        for name, layout in self.layouts.items():
            for s in layout["settings"]:
                with self.subTest(layout=name, key=s["key"]):
                    self.assertGreater(len(s["reason"]), 10)

    def test_layouts_are_meaningfully_different(self):
        def dock(layout, key):
            return next(s["value"] for s in layout["settings"]
                        if s["schema"].endswith("jeronix-dock") and s["key"] == key)
        positions = {name: dock(l, "position") for name, l in self.layouts.items()}
        behaviors = {name: dock(l, "behavior") for name, l in self.layouts.items()}
        self.assertEqual(len(set(positions.values())), 3, positions)
        self.assertEqual(len(set(behaviors.values())), 3, behaviors)
        keys = {name: {(s["schema"], s["key"]) for s in l["settings"]} for name, l in self.layouts.items()}
        self.assertIn(("org.gnome.desktop.wm.preferences", "num-workspaces"), keys["studio"])
        self.assertNotIn(("org.gnome.desktop.wm.preferences", "num-workspaces"), keys["pure"])

    def test_every_layout_replaces_ubuntu_dock_with_jeronix_dock(self):
        for name, layout in self.layouts.items():
            with self.subTest(layout=name):
                ext = layout["extensions"]
                self.assertIn("jeronix-dock@jeronix", ext["enable"])
                self.assertIn("ubuntu-dock@ubuntu.com", ext["disable"])

    def test_switchable_extensions_are_only_jeronix_and_ubuntu_shell_parts(self):
        self.assertEqual(layout_tool.SWITCHABLE - JERONIX_EXTENSIONS,
                         {"ubuntu-dock@ubuntu.com", "ding@rastersoft.com"})

    def test_allowlist_excludes_anything_that_can_run_code_or_toggle_extensions_directly(self):
        forbidden = {("org.gnome.shell", "enabled-extensions"), ("org.gnome.shell", "disabled-extensions"),
                     ("org.gnome.shell", "disable-user-extensions")}
        for schema, keys in layout_tool.ALLOWED.items():
            self.assertNotIn("media-keys", schema)
            self.assertNotIn("custom", schema)
            for key in keys:
                self.assertNotIn((schema, key), forbidden)
                self.assertNotRegex(key, r"command|exec|autostart|custom")

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
            "unknown asset": lambda l: key(l, "picture-uri").update(value={"asset": "../../etc/passwd"}),
            "unsupported shell": lambda l: l.update(gnome_shell=["49"]),
            "bad version": lambda l: l.update(version="1"),
            "old schema version": lambda l: l.update(schema=1),
            "object value": lambda l: l["settings"][0].update(value={"x": 1}),
            "foreign extension": lambda l: l["extensions"]["enable"].append("evil@example.com"),
            "enable and disable": lambda l: l["extensions"]["disable"].append("jeronix-dock@jeronix"),
            "unknown extensions field": lambda l: l["extensions"].update(run=["x"]),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                broken = copy.deepcopy(self.pure)
                mutate(broken)
                self.assertTrue(layout_tool.check_structure(broken))

    def test_switched_lists(self):
        layout = {"extensions": {"enable": ["jeronix-dock@jeronix"], "disable": ["ubuntu-dock@ubuntu.com"]}}
        enabled, disabled = layout_tool.switched_lists(
            layout, ["user-ext@x", "ubuntu-dock@ubuntu.com"], ["jeronix-dock@jeronix", "other@y"])
        self.assertEqual(enabled, ["user-ext@x", "jeronix-dock@jeronix"])
        self.assertEqual(disabled, ["other@y", "ubuntu-dock@ubuntu.com"])

    def test_restore_guard_blocks_foreign_extensions(self):
        layout_tool._check_extension_restore("enabled-extensions", ["jeronix-dock@jeronix"], [])
        with self.assertRaises(layout_tool.LayoutError):
            layout_tool._check_extension_restore("enabled-extensions", ["evil@x"], [])
        with self.assertRaises(layout_tool.LayoutError):
            layout_tool._check_extension_restore("disabled-extensions", [], ["users-own@ext"])


@unittest.skipUnless(has_gsettings_schemas(), "GNOME GSettings schemas not installed")
class LayoutGSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        import jeronix_design
        cls._built = tempfile.TemporaryDirectory()
        jeronix_design.build(Path(cls._built.name), parts=("extensions",))
        cls.extensions = Path(cls._built.name) / "extensions"

    @classmethod
    def tearDownClass(cls):
        cls._built.cleanup()

    def setUp(self):
        self.box = Sandbox(self.extensions)

    def tearDown(self):
        self.box.close()

    def write_layout(self, mutate, source=PURE):
        layout = json.loads(source.read_text(encoding="utf-8"))
        mutate(layout)
        path = self.box.root / "layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return path

    def test_layouts_validate_against_installed_schemas(self):
        for path in ALL:
            with self.subTest(layout=path.stem):
                self.assertIn("valid", self.box.run("validate", path).stdout)

    def test_jeronix_settings_need_the_extensions_installed(self):
        self.box.env["JERONIX_EXTENSION_DIRS"] = str(self.box.root / "nowhere")
        result = self.box.run("validate", PURE, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("install the JERONIX extensions", result.stderr)
        self.assertIn("is not installed, so the layout cannot enable it", result.stderr)

    def test_type_and_range_errors_are_caught_before_writing(self):
        cases = {
            "string for bool": lambda l: key(l, "enable-hot-corners").update(value="yes"),
            "enum out of range": lambda l: key(l, "color-scheme").update(value="prefer-purple"),
            "dock position out of range": lambda l: next(
                s for s in l["settings"] if s["key"] == "position").update(value="top"),
            "missing required key": lambda l: l["settings"].append(
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
        out = self.box.run("plan", PURE).stdout
        self.assertIn("extension ubuntu-dock@ubuntu.com: disable", out)
        self.assertFalse(self.box.keyfile.exists() and self.box.keyfile.read_text().strip())

    def test_apply_then_restore_round_trip_for_every_layout(self):
        self.box.install_wallpapers()
        # A customized value must come back exactly, the user's own extension
        # must survive, and untouched keys must return to their defaults.
        self.box.keyfile.write_text(
            "[org/gnome/desktop/interface]\nclock-show-weekday=false\naccent-color='teal'\n"
            "[org/gnome/shell]\nenabled-extensions=['users-own@example.com']\n", encoding="utf-8")
        probe = [("org.gnome.desktop.interface", "accent-color"), ("org.gnome.desktop.interface", "clock-show-weekday"),
                 ("org.gnome.desktop.interface", "color-scheme"), ("org.gnome.mutter", "dynamic-workspaces"),
                 ("org.gnome.shell", "enabled-extensions"), ("org.gnome.shell", "disabled-extensions"),
                 ("org.gnome.shell.extensions.jeronix-dock", "position"),
                 ("org.gnome.desktop.wm.keybindings", "switch-to-workspace-1")]
        before = {k: self.box.get(*k) for k in probe}
        for path in ALL:
            with self.subTest(layout=path.stem):
                layout = json.loads(path.read_text(encoding="utf-8"))
                self.box.run("apply", path)
                dock = next(s["value"] for s in layout["settings"] if s["key"] == "position")
                self.assertEqual(self.box.get("org.gnome.shell.extensions.jeronix-dock", "position"), f"'{dock}'")
                enabled = self.box.get("org.gnome.shell", "enabled-extensions")
                disabled = self.box.get("org.gnome.shell", "disabled-extensions")
                for uuid in layout["extensions"]["enable"]:
                    self.assertIn(uuid, enabled)
                for uuid in layout["extensions"]["disable"]:
                    self.assertIn(uuid, disabled)
                self.assertIn("users-own@example.com", enabled, "the user's own extension is kept")
                self.box.run("restore")
                self.assertEqual({k: self.box.get(*k) for k in probe}, before)
        text = self.box.keyfile.read_text(encoding="utf-8")
        self.assertNotIn("color-scheme", text, "default-valued keys are reset, not written")
        self.assertNotIn("disabled-extensions", text)

    def test_studio_rebinds_workspace_shortcuts(self):
        self.box.install_wallpapers()
        self.box.run("apply", LAYOUTS / "studio.json")
        self.assertEqual(self.box.get("org.gnome.desktop.wm.keybindings", "switch-to-workspace-2"), "['<Super>2']")
        self.assertEqual(self.box.get("org.gnome.shell.keybindings", "switch-to-application-2"), "[]")
        self.assertEqual(self.box.get("org.gnome.desktop.wm.preferences", "num-workspaces"), "4")

    def test_tampered_snapshot_is_refused(self):
        snap_dir = self.box.root / "state" / "jeronix" / "layout-snapshots"
        snap_dir.mkdir(parents=True)
        (snap_dir / "x.json").write_text(json.dumps({"schema": 2, "entries": [
            {"schema": "org.gnome.shell", "key": "enabled-extensions", "user_value": "['evil@example.com']"}]}))
        result = self.box.run("restore", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("non-JERONIX extensions", result.stderr)
        (snap_dir / "x.json").write_text(json.dumps({"schema": 2, "entries": [
            {"schema": "org.gnome.settings-daemon.plugins.media-keys", "key": "custom-keybindings",
             "user_value": "@as []"}]}))
        result = self.box.run("restore", check=False)
        self.assertIn("not an allowed layout setting", result.stderr)


if __name__ == "__main__":
    unittest.main()
