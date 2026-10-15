# SPDX-License-Identifier: GPL-3.0-or-later
"""Static checks for every GNOME Shell extension under desktop/extensions."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = ROOT / "desktop" / "extensions"
PLATFORM = json.loads((ROOT / "config" / "platform.json").read_text(encoding="utf-8"))
UUID = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$")


def extension_dirs():
    return sorted(p for p in EXTENSIONS.iterdir() if (p / "metadata.json").exists())


class ExtensionManifestTests(unittest.TestCase):
    def test_at_least_one_extension(self):
        self.assertTrue(extension_dirs())

    def test_manifests(self):
        supported = PLATFORM["gnome_shell"]["supported_versions"]
        for ext in extension_dirs():
            with self.subTest(extension=ext.name):
                meta = json.loads((ext / "metadata.json").read_text(encoding="utf-8"))
                for key in ("uuid", "name", "description", "shell-version"):
                    self.assertIn(key, meta)
                self.assertRegex(meta["uuid"], UUID)
                # Source directory is named after the part before '@'.
                self.assertEqual(meta["uuid"].split("@")[0], ext.name)
                self.assertEqual(meta["shell-version"], supported,
                                 "shell-version must match config/platform.json")
                self.assertTrue((ext / "extension.js").exists())

    def test_extensions_use_esm_default_export(self):
        for ext in extension_dirs():
            with self.subTest(extension=ext.name):
                src = (ext / "extension.js").read_text(encoding="utf-8")
                self.assertRegex(src, r"export default class \w+ extends Extension")
                self.assertIn("enable()", src)
                self.assertIn("disable()", src)
                self.assertNotIn("imports.", src, "legacy imports.* API is not supported")


@unittest.skipUnless(shutil.which("gjs"), "gjs not installed")
class JavaScriptSyntaxTests(unittest.TestCase):
    def test_extension_js_parses(self):
        # gjs parses a module before resolving its imports, so syntax errors
        # are reported first; the import of Shell-only modules
        # (resource:///org/gnome/shell/...) then fails, which is expected
        # outside GNOME Shell. Extension modules have no top-level side effects.
        for js in sorted(EXTENSIONS.rglob("*.js")):
            with self.subTest(file=str(js.relative_to(ROOT))):
                result = subprocess.run(["gjs", "-m", str(js)],
                                        capture_output=True, text=True, timeout=30)
                self.assertNotIn("SyntaxError", result.stderr)
                if result.returncode != 0:
                    self.assertIn("resource:///org/gnome/shell/", result.stderr,
                                  f"unexpected gjs failure:\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
