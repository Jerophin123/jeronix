# SPDX-License-Identifier: GPL-3.0-or-later
"""Keeps the documentation honest: links resolve, referenced files and
commands exist, and the asset and layout tables match the real files."""

import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_layout  # noqa: E402

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`]+)`")
REPO_PATH = re.compile(r"^(?:scripts|desktop|design|docs|tests|config)/[\w./@-]+$")
LAYOUT_CMD = re.compile(r"jeronix_layout\.py (\w+)")
DESIGN_CMD = re.compile(r"jeronix_design\.py (\w+)")


def markdown_files():
    return sorted(p for p in ROOT.rglob("*.md")
                  if not any(part in (".git", "out", "node_modules") for part in p.relative_to(ROOT).parts))


class DocumentationTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        for md in markdown_files():
            for target in LINK.findall(md.read_text(encoding="utf-8")):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                with self.subTest(doc=str(md.relative_to(ROOT)), link=target):
                    self.assertTrue((md.parent / target.split("#")[0]).exists())

    def test_referenced_repo_paths_exist(self):
        for md in markdown_files():
            for code in CODE.findall(md.read_text(encoding="utf-8")):
                path = code.split()[0] if code.split() else ""
                if REPO_PATH.match(path):
                    with self.subTest(doc=str(md.relative_to(ROOT)), path=path):
                        self.assertTrue((ROOT / path).exists())

    def test_documented_commands_exist(self):
        layout_cmds = {"validate", "plan", "apply", "snapshots", "restore"}
        design_cmds = {"build", "check"}
        for md in markdown_files():
            text = md.read_text(encoding="utf-8")
            for cmd in LAYOUT_CMD.findall(text):
                with self.subTest(doc=md.name, cmd=cmd):
                    self.assertIn(cmd, layout_cmds)
            for cmd in DESIGN_CMD.findall(text):
                with self.subTest(doc=md.name, cmd=cmd):
                    self.assertIn(cmd, design_cmds)

    def test_asset_table_matches_icons(self):
        icons = ROOT / "design" / "icons"
        readme = (icons / "README.md").read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| `([\w.-]+\.svg)` \| (\d+x\d+) \|", readme, re.M))
        self.assertEqual(set(rows), {p.name for p in icons.glob("*.svg")})
        for name, size in rows.items():
            with self.subTest(svg=name):
                root = ET.parse(icons / name).getroot()
                self.assertEqual(f"{root.attrib['width']}x{root.attrib['height']}", size)

    def test_layout_table_matches_pure(self):
        readme = (ROOT / "desktop" / "layouts" / "README.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `([\w.-]+)` \| `([\w-]+)` \|", readme, re.M))
        pure = json.loads((ROOT / "desktop" / "layouts" / "pure.json").read_text(encoding="utf-8"))
        self.assertEqual(documented, {(s["schema"], s["key"]) for s in pure["settings"]})

    def test_layout_assets_documented(self):
        readme = (ROOT / "desktop" / "layouts" / "README.md").read_text(encoding="utf-8")
        for asset in jeronix_layout.ASSETS:
            self.assertIn(f"`{asset}`", readme)

    def test_manual_session_test_not_claimed(self):
        # Until someone records a live-session run, docs must say it is pending.
        text = (ROOT / "docs" / "development" / "desktop-identity.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"\*\*not been\s+performed yet\*\*")


if __name__ == "__main__":
    unittest.main()
