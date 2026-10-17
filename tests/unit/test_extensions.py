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


class ExtensionSchemaTests(unittest.TestCase):
    def test_settings_schema_matches_metadata(self):
        for ext in extension_dirs():
            meta = json.loads((ext / "metadata.json").read_text(encoding="utf-8"))
            schemas = sorted((ext / "schemas").glob("*.gschema.xml")) if (ext / "schemas").is_dir() else []
            with self.subTest(extension=ext.name):
                if "settings-schema" not in meta:
                    self.assertEqual(schemas, [], "schema files without settings-schema in metadata")
                    continue
                self.assertEqual(meta["settings-schema"], f"org.gnome.shell.extensions.{ext.name}")
                self.assertEqual([s.name for s in schemas], [f"{meta['settings-schema']}.gschema.xml"])
                text = schemas[0].read_text(encoding="utf-8")
                self.assertIn(f'id="{meta["settings-schema"]}"', text)
                self.assertIn(f'path="/org/gnome/shell/extensions/{ext.name}/"', text)

    @unittest.skipUnless(shutil.which("glib-compile-schemas"), "glib-compile-schemas not installed")
    def test_schemas_compile_strictly(self):
        for ext in extension_dirs():
            if not (ext / "schemas").is_dir():
                continue
            with self.subTest(extension=ext.name):
                result = subprocess.run(["glib-compile-schemas", "--strict", "--dry-run", str(ext / "schemas")],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_compiled_or_generated_files_in_source(self):
        for ext in extension_dirs():
            with self.subTest(extension=ext.name):
                self.assertFalse(list(ext.rglob("gschemas.compiled")))
                self.assertFalse([p for p in ext.glob("stylesheet*.css")])

    def test_every_extension_documents_itself(self):
        for ext in extension_dirs():
            with self.subTest(extension=ext.name):
                self.assertTrue((ext / "README.md").is_file())

    def test_enable_is_idempotent(self):
        # GNOME 50 can call enable() twice when enabled-extensions and
        # disabled-extensions change together (seen in a live session), so
        # every extension that creates objects must ignore a second call.
        for ext in extension_dirs():
            src = (ext / "extension.js").read_text(encoding="utf-8")
            body = re.search(r"\n    enable\(\) \{(.*?)\n    \}\n", src, re.S).group(1)
            if not body.strip():
                continue  # stylesheet-only extension
            with self.subTest(extension=ext.name):
                code = [line for line in body.splitlines() if line.strip() and not line.strip().startswith("//")]
                self.assertRegex(code[0], r"^\s*if \(this\._\w+\)", "first statement must guard re-entry")

    def test_no_private_shell_internals(self):
        # Extensions may use the shell's exported classes and functions, but
        # not monkey-patch prototypes (InjectionManager is the supported way).
        for js in sorted(EXTENSIONS.rglob("*.js")):
            with self.subTest(file=js.name):
                src = js.read_text(encoding="utf-8")
                self.assertNotRegex(src, r"\.prototype\.\w+\s*=")
                self.assertNotIn("global.context.unsafe_mode", src)


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
