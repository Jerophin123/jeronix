# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistency checks for design/tokens/tokens.json and brand artwork."""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "design" / "tokens" / "tokens.json"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def relative_luminance(hex_color):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b):
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class DesignTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = json.loads(TOKENS.read_text(encoding="utf-8"))

    def test_schema_and_version(self):
        self.assertEqual(self.tokens["schema"], 1)
        self.assertRegex(self.tokens["version"], r"^\d+\.\d+\.\d+$")

    def test_modes_define_identical_roles(self):
        dark = self.tokens["color"]["dark"]
        light = self.tokens["color"]["light"]
        self.assertEqual(set(dark), set(light))

    def test_colors_are_hex(self):
        for mode, palette in self.tokens["color"].items():
            for role, value in palette.items():
                self.assertRegex(value, HEX, f"{mode}.{role}")
        for name, value in self.tokens["brand"].items():
            self.assertRegex(value, HEX, f"brand.{name}")

    def test_contrast_pairs_meet_minimums(self):
        for mode, palette in self.tokens["color"].items():
            for fg, bg, minimum in self.tokens["contrast"]["pairs"]:
                with self.subTest(mode=mode, fg=fg, bg=bg):
                    ratio = contrast_ratio(palette[fg], palette[bg])
                    self.assertGreaterEqual(
                        ratio, minimum,
                        f"{mode}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1")

    def test_scales_are_ascending(self):
        spacing = self.tokens["spacing-px"]
        self.assertEqual(spacing, sorted(set(spacing)))
        icons = self.tokens["icon-size-px"]
        self.assertEqual(icons, sorted(set(icons)))
        durations = list(self.tokens["motion"]["duration-ms"].values())
        self.assertEqual(durations, sorted(durations))

    def test_brand_artwork_uses_token_colors(self):
        allowed = {v.upper() for v in self.tokens["brand"].values()}
        for mode in self.tokens["color"].values():
            allowed |= {v.upper() for v in mode.values()}
        svgs = sorted((ROOT / "design" / "icons").glob("*.svg"))
        self.assertTrue(svgs, "no brand SVGs found")
        for svg in svgs:
            with self.subTest(svg=svg.name):
                ET.parse(svg)  # well-formed XML
                used = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", svg.read_text(encoding="utf-8"))}
                self.assertLessEqual(used, allowed, f"colors not in tokens: {used - allowed}")


if __name__ == "__main__":
    unittest.main()
