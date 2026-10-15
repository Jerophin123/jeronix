# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistency checks for design/tokens/tokens.json."""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_design as design  # noqa: E402

TOKENS = ROOT / "design" / "tokens" / "tokens.json"


class DesignTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = json.loads(TOKENS.read_text(encoding="utf-8"))

    def test_tokens_are_valid(self):
        self.assertEqual(design.validate_tokens(self.tokens), [])

    def test_required_roles(self):
        required = {"surface", "surface-raised", "surface-overlay", "panel", "on-panel", "border",
                    "text", "text-secondary", "text-muted", "accent", "accent-strong", "on-accent",
                    "focus-ring", "success", "warning", "danger", "panel-accent", "accent-secondary"}
        for mode in design.MODES:
            with self.subTest(mode=mode):
                self.assertLessEqual(required, set(self.tokens["color"][mode]))

    def test_contrast_pairs_meet_minimums(self):
        for scope, fg, bg, ratio, minimum in design.contrast_report(self.tokens):
            with self.subTest(scope=scope, fg=fg, bg=bg):
                self.assertGreaterEqual(ratio, minimum, f"{scope}: {fg} on {bg} is {ratio:.2f}:1")

    def test_contrast_pairs_reference_real_roles(self):
        roles = set(design.palette(self.tokens, "dark"))
        for fg, bg, _ in self.tokens["contrast"]["pairs"]:
            self.assertIn(fg, roles)
            self.assertIn(bg, roles)
        for fg, bg, _ in self.tokens["contrast"]["brand-pairs"]:
            self.assertIn(fg, self.tokens["brand"])
            self.assertIn(bg, self.tokens["brand"])

    def test_contrast_math(self):
        self.assertAlmostEqual(design.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(design.contrast_ratio("#777777", "#777777"), 1.0)
        self.assertEqual(design.blend("#FFFFFF", "#000000", 0.5), "#808080")

    def test_validator_rejects_bad_tokens(self):
        cases = {
            "bad hex": lambda t: t["color"]["dark"].update(text="#ECEFE"),
            "mode role mismatch": lambda t: t["color"]["light"].pop("panel"),
            "off-grid spacing": lambda t: t["spacing-px"].update(md=15),
            "unknown wallpaper color": lambda t: t["wallpaper"]["dark"].update(line="nope"),
            "opacity out of range": lambda t: t["interaction"].update({"hover-opacity": 1.5}),
            "missing section": lambda t: t.pop("motion"),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                broken = copy.deepcopy(self.tokens)
                mutate(broken)
                self.assertTrue(design.validate_tokens(broken))

    def test_low_contrast_is_detected(self):
        broken = copy.deepcopy(self.tokens)
        broken["color"]["dark"]["text-muted"] = "#3A3F3B"
        failing = [r for r in design.contrast_report(broken) if r[3] < r[4]]
        self.assertTrue(any(r[1] == "text-muted" for r in failing))


if __name__ == "__main__":
    unittest.main()
