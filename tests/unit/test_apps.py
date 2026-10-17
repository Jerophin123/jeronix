# SPDX-License-Identifier: GPL-3.0-or-later
"""Logic of the JERONIX applications without a display: launcher catalog and
search, system information collection, layout previews, app styling,
desktop entries and staging. The windows themselves are exercised in a real
shell by tests/integration/apps_lifecycle.py."""

import configparser
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "packaging"))

from jeronix_common import paths, previews, style  # noqa: E402
from launcher import catalog  # noqa: E402
from system_info import collect  # noqa: E402

import jeronix_apps  # noqa: E402


class FakeInfo:
    def __init__(self, app_id, name, show=True, generic="", keywords=(), categories="", desc="", exe=""):
        self._v = (app_id, name, show, generic, list(keywords), categories, desc, exe)

    def get_id(self): return self._v[0]  # noqa: E704
    def get_display_name(self): return self._v[1]  # noqa: E704
    def get_name(self): return self._v[1]  # noqa: E704
    def should_show(self): return self._v[2]  # noqa: E704
    def get_generic_name(self): return self._v[3]  # noqa: E704
    def get_keywords(self): return self._v[4]  # noqa: E704
    def get_categories(self): return self._v[5]  # noqa: E704
    def get_description(self): return self._v[6]  # noqa: E704
    def get_executable(self): return self._v[7]  # noqa: E704


INFOS = [
    FakeInfo("org.gnome.TextEditor.desktop", "Text Editor", generic="Text Editor", keywords=["notepad", "txt"],
             categories="GNOME;GTK;Utility;TextEditor;", exe="/usr/bin/gnome-text-editor"),
    FakeInfo("org.gnome.Terminal.desktop", "Terminal", keywords=["shell", "prompt"], categories="System;",
             exe="ptyxis"),
    FakeInfo("firefox_firefox.desktop", "Firefox Web Browser", generic="Web Browser", categories="Network;",
             desc="Browse the World Wide Web"),
    FakeInfo("hidden.desktop", "Hidden", show=False),
    FakeInfo("org.gnome.TextEditor.desktop", "Duplicate"),
    FakeInfo("org.gnome.Settings.desktop", "Settings", categories="GNOME;Settings;", keywords=["preferences"]),
]


class LauncherCatalogTests(unittest.TestCase):
    def setUp(self):
        self.entries = catalog.load_entries(INFOS)

    def test_hidden_and_duplicate_entries_are_dropped(self):
        self.assertEqual([e.name for e in self.entries], ["Firefox Web Browser", "Settings", "Terminal", "Text Editor"])

    def test_search_ranks_name_prefix_first(self):
        self.assertEqual(catalog.search(self.entries, "te")[0].name, "Terminal")
        self.assertEqual([e.name for e in catalog.search(self.entries, "text")], ["Text Editor"])

    def test_search_matches_keywords_generic_names_and_executables(self):
        self.assertEqual(catalog.search(self.entries, "notepad")[0].name, "Text Editor")
        self.assertEqual(catalog.search(self.entries, "browser")[0].name, "Firefox Web Browser")
        self.assertEqual(catalog.search(self.entries, "ptyxis")[0].name, "Terminal")
        self.assertEqual(catalog.search(self.entries, "preferences")[0].name, "Settings")

    def test_every_word_must_match(self):
        self.assertEqual(catalog.search(self.entries, "web browser")[0].name, "Firefox Web Browser")
        self.assertEqual(catalog.search(self.entries, "web terminal"), [])

    def test_recent_apps_win_ties(self):
        # Terminal and Text Editor both start with "t": alphabetical unless one was used recently.
        self.assertEqual(catalog.search(self.entries, "t")[0].name, "Terminal")
        recent = ["org.gnome.TextEditor.desktop"]
        self.assertEqual(catalog.search(self.entries, "t", recent)[0].name, "Text Editor")

    def test_categories(self):
        self.assertEqual([e.name for e in catalog.in_category(self.entries, "Utility")], ["Text Editor"])
        favorites = ["org.gnome.Terminal.desktop", "missing.desktop"]
        self.assertEqual([e.name for e in catalog.in_category(self.entries, "favorites", favorites)], ["Terminal"])
        cats = [c[0] for c in catalog.categories_with_entries(self.entries, favorites, [])]
        self.assertEqual(cats[:2], ["all", "favorites"])
        self.assertNotIn("recent", cats, "empty categories are hidden")
        self.assertNotIn("Game", cats)

    def test_recent_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = catalog.RecentStore(Path(tmp) / "sub" / "recent.json")
            self.assertEqual(store.load(), [])
            for i in range(20):
                store.add(f"app{i}")
            store.add("app5")
            ids = store.load()
            self.assertEqual(ids[0], "app5")
            self.assertEqual(len(ids), catalog.RECENT_LIMIT)
            self.assertEqual(len(set(ids)), len(ids))
            (Path(tmp) / "sub" / "recent.json").write_text("not json")
            self.assertEqual(store.load(), [])


class SystemInfoTests(unittest.TestCase):
    def test_parsers_with_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "os-release").write_text('PRETTY_NAME="Ubuntu 26.04.1 LTS"\nID=ubuntu\n# comment\n')
            (tmp / "cpuinfo").write_text("processor\t: 0\nmodel name\t: Test   CPU  9000\n"
                                         "processor\t: 1\nmodel name\t: Test CPU 9000\n")
            (tmp / "meminfo").write_text("MemTotal:        8000000 kB\nMemFree: 1 kB\n")
            self.assertEqual(collect.parse_env_file(tmp / "os-release")["PRETTY_NAME"], "Ubuntu 26.04.1 LTS")
            self.assertEqual(collect.cpu(tmp / "cpuinfo"), {"model": "Test CPU 9000", "threads": 2})
            self.assertEqual(collect.memory_bytes(tmp / "meminfo"), 8000000 * 1024)
            self.assertEqual(collect.parse_env_file(tmp / "missing"), {})
            self.assertEqual(collect.graphics(tmp / "no-drm"), [])

    def test_human_bytes(self):
        self.assertEqual(collect.human_bytes(512), "512 B")
        self.assertEqual(collect.human_bytes(8 * 1024 ** 3), "8.0 GB")

    def test_collect_and_report_on_this_machine(self):
        info = collect.collect()
        for key in ("JERONIX", "Base system", "Kernel", "GNOME Shell", "Processor", "Memory"):
            self.assertIn(key, info)
        text = collect.report(info, {"jeronix-dock@jeronix": "active"}, {"GTK": "4.22"})
        self.assertIn("JERONIX system report", text)
        self.assertIn("jeronix-dock@jeronix: active", text)
        for secret in ("password", "token", "BEGIN"):
            self.assertNotIn(secret, text.lower() if secret != "BEGIN" else text)


class PreviewAndStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = style.load_tokens()
        cls.layouts = {p.stem: json.loads(p.read_text()) for p in (ROOT / "desktop" / "layouts").glob("*.json")}

    def test_previews_are_valid_svg_and_reflect_the_dock(self):
        svgs = {}
        for name, layout in self.layouts.items():
            for mode in ("dark", "light"):
                svg = previews.layout_preview_svg(layout, self.tokens, mode)
                ET.fromstring(svg)
                svgs[(name, mode)] = svg
        self.assertEqual(len({svgs[(n, "dark")] for n in self.layouts}), len(self.layouts),
                         "each layout looks different")
        self.assertIn("stroke-dasharray", svgs[("studio", "dark")], "autohide dock is drawn as hidden")
        self.assertNotIn("stroke-dasharray", svgs[("classic", "dark")])

    def test_app_css_uses_token_colors(self):
        for mode in ("dark", "light"):
            css = style.css_for(self.tokens, mode)
            p = self.tokens["color"][mode]
            self.assertIn(f"--window-bg-color: {p['surface']};", css)
            self.assertIn(f"--accent-bg-color: {p['accent']};", css)
            self.assertEqual(css.count("{"), css.count("}"))

    def test_paths_from_checkout(self):
        self.assertEqual(paths.tokens_file(), ROOT / "design" / "tokens" / "tokens.json")
        self.assertEqual(paths.layouts_dir(), ROOT / "desktop" / "layouts")
        self.assertTrue(hasattr(paths.layout_tool(), "apply"))


class DesktopEntryAndStagingTests(unittest.TestCase):
    def test_desktop_templates(self):
        for app_id in jeronix_apps.DESKTOP_IDS:
            with self.subTest(app=app_id):
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str
                parser.read(ROOT / "apps" / "desktop" / f"{app_id}.desktop.in")
                entry = parser["Desktop Entry"]
                self.assertEqual(entry["Icon"], app_id)
                self.assertTrue(entry["Exec"].startswith("@PYTHON@ @APPS@/"))
                script = entry["Exec"].split()[1].replace("@APPS@/", "")
                self.assertTrue((ROOT / "apps" / script).is_file(), script)
                self.assertTrue(entry["Categories"].endswith(";"))

    def test_stage_into_installed_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp) / "share"
            created = jeronix_apps.stage(share, python="/usr/bin/python3", autostart_dir=Path(tmp) / "autostart")
            self.assertTrue(all(str(p).startswith(tmp) for p in created))
            base = share / "jeronix"
            for rel in ("apps/launcher/launcher.py", "design/tokens.json", "layouts/pure.json",
                        "scripts/jeronix_layout.py", "config/platform.json", "branding/jeronix-lockup-on-dark.svg"):
                self.assertTrue((base / rel).is_file(), rel)
            self.assertFalse(list(base.rglob("__pycache__")))
            desktop = (share / "applications" / "io.jeronix.Launcher.desktop").read_text()
            self.assertIn(f"Exec=/usr/bin/python3 {base}/apps/launcher/launcher.py", desktop)
            autostart = (Path(tmp) / "autostart" / "io.jeronix.Welcome.desktop").read_text()
            self.assertIn("--first-run", autostart)
            # The staged apps find their data in the installed layout.
            code = ("import sys; sys.path.insert(0, sys.argv[1]); from jeronix_common import paths; "
                    "print(paths.tokens_file()); print(paths.layouts_dir())")
            moved = Path(tmp) / "elsewhere"
            shutil.copytree(base, moved / "jeronix")
            out = subprocess.run([sys.executable, "-c", code, str(moved / "jeronix" / "apps")],
                                 capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(out, [str(moved / "jeronix" / "design" / "tokens.json"),
                                   str(moved / "jeronix" / "layouts")])

    def test_apps_compile(self):
        for py in sorted((ROOT / "apps").rglob("*.py")):
            with self.subTest(file=str(py.relative_to(ROOT))):
                compile(py.read_text(encoding="utf-8"), str(py), "exec")


if __name__ == "__main__":
    unittest.main()
