# SPDX-License-Identifier: GPL-3.0-or-later
"""Development install and removal of the desktop identity, in a temporary
XDG tree with no session bus (so gnome-extensions cannot reach a real shell).
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "install-desktop-dev.sh"
UUID = "jeronix-shell-theme@jeronix"


@unittest.skipUnless(shutil.which("bash") and shutil.which("gsettings"), "bash and gsettings required")
class DevInstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for sub in ("home", "data", "config/glib-2.0/settings", "tmp"):
            (self.root / sub).mkdir(parents=True)
        self.data = self.root / "data"
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(self.root / "home"),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "TMPDIR": str(self.root / "tmp"),
            "GSETTINGS_BACKEND": "keyfile",
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *args, script=INSTALL):
        return subprocess.run(["bash", str(script), *args], env=self.env,
                              capture_output=True, text=True, timeout=180)

    def files(self):
        return sorted(p for p in self.data.rglob("*") if p.is_file())

    def test_install_then_remove(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Nothing has been switched on", result.stdout)

        ext = self.data / "gnome-shell" / "extensions" / UUID
        for name in ("metadata.json", "extension.js", "stylesheet-dark.css", "stylesheet-light.css"):
            self.assertTrue((ext / name).is_file(), name)
        self.assertEqual(json.loads((ext / "metadata.json").read_text())["uuid"], UUID)
        for other in ("jeronix-panel@jeronix", "jeronix-dock@jeronix"):
            other_dir = self.data / "gnome-shell" / "extensions" / other
            self.assertTrue((other_dir / "schemas" / "gschemas.compiled").is_file(), other)
            self.assertTrue((other_dir / "stylesheet-dark.css").is_file(), other)
        self.assertTrue((self.data / "gnome-shell/extensions/jeronix-quick-settings@jeronix/inhibitor.js").is_file())

        props = ET.parse(self.data / "gnome-background-properties" / "jeronix.xml").getroot()
        wallpaper = props.find("wallpaper")
        for tag in ("filename", "filename-dark"):
            self.assertTrue(Path(wallpaper.find(tag).text).is_file(), tag)

        for icon in ("16x16/apps/jeronix.png", "256x256/apps/jeronix.png", "scalable/apps/jeronix.svg",
                     "symbolic/apps/jeronix-symbolic.svg"):
            self.assertTrue((self.data / "icons" / "hicolor" / icon).is_file(), icon)

        manifest = (self.data / "jeronix" / "dev-install.manifest").read_text().split("\n")
        self.assertTrue(all(line.startswith(str(self.data)) for line in manifest if line))
        self.assertEqual(list((self.root / "tmp").iterdir()), [], "build directory is cleaned up")
        self.assertEqual(list((self.root / "config").rglob("keyfile")), [], "install changes no settings")

        result = self.run_script("--remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.files(), [], "remove deletes everything it installed")

    def test_install_is_repeatable(self):
        self.assertEqual(self.run_script().returncode, 0)
        first = self.files()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.files(), first)

    def test_remove_refuses_while_wallpaper_in_use(self):
        self.assertEqual(self.run_script().returncode, 0)
        uri = (self.data / "backgrounds" / "jeronix" / "jeronix-dark.png").as_uri()
        (self.root / "config" / "glib-2.0" / "settings" / "keyfile").write_text(
            f"[org/gnome/desktop/background]\npicture-uri-dark='{uri}'\n", encoding="utf-8")
        result = self.run_script("--remove")
        self.assertEqual(result.returncode, 1)
        self.assertIn("jeronix_layout.py restore", result.stderr)
        self.assertTrue((self.data / "backgrounds" / "jeronix" / "jeronix-dark.png").is_file())
        self.assertEqual(self.run_script("--remove", "--force").returncode, 0)
        self.assertEqual(self.files(), [])

    def test_remove_without_install_is_harmless(self):
        result = self.run_script("--remove")
        self.assertEqual(result.returncode, 0)
        self.assertIn("nothing to remove", result.stdout)

    def test_manifest_cannot_delete_outside_data_dir(self):
        outside = self.root / "home" / "keep-me"
        outside.write_text("x")
        (self.data / "jeronix").mkdir()
        (self.data / "jeronix" / "dev-install.manifest").write_text(f"{outside}\n")
        self.assertEqual(self.run_script("--remove").returncode, 0)
        self.assertTrue(outside.exists())

    def test_extension_installer_refuses_theme_without_build(self):
        result = self.run_script("jeronix-shell-theme", script=ROOT / "scripts" / "install-extension-dev.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("install-desktop-dev.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
