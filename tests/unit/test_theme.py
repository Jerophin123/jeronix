# SPDX-License-Identifier: GPL-3.0-or-later
"""Static checks for the generated GNOME Shell theme.

The computed-style check inside a real shell is
tests/integration/theme_lifecycle.py.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_design as design  # noqa: E402

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
HEX_IN_CSS = re.compile(r"#[0-9A-Fa-f]{6}\b")
RGBA = re.compile(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)")


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rules(css):
    """[(selectors, {property: value})] of a flat (non-nested) stylesheet."""
    out = []
    for selectors, body in RULE.findall(strip_comments(css)):
        decls = {}
        for decl in body.split(";"):
            if ":" in decl:
                prop, value = decl.split(":", 1)
                decls[prop.strip()] = value.strip()
        out.append((tuple(s.strip() for s in selectors.split(",")), decls))
    return out


class ShellThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = design.load_tokens()
        cls.platform = design.load_platform()
        cls.template = design.THEME_TEMPLATE.read_text(encoding="utf-8")
        cls.css = {m: design.render_shell_css(cls.tokens, m, cls.platform) for m in design.MODES}

    def test_every_placeholder_is_a_token(self):
        variables = design.theme_variables(self.tokens, "dark", self.platform)
        self.assertLessEqual(set(design.PLACEHOLDER.findall(self.template)), set(variables))

    def test_unknown_placeholder_is_an_error(self):
        with self.assertRaises(ValueError):
            design.render_template("a { color: @no-such-token@; }", {})

    def test_no_placeholder_left_and_braces_balanced(self):
        for mode, css in self.css.items():
            with self.subTest(mode=mode):
                self.assertNotRegex(css, r"@[a-z0-9-]+@")
                body = strip_comments(css)
                self.assertEqual(body.count("{"), body.count("}"))
                self.assertNotIn("{{", body)

    def test_generation_is_deterministic(self):
        for mode in design.MODES:
            self.assertEqual(self.css[mode], design.render_shell_css(self.tokens, mode, self.platform))

    def test_variants_share_selectors(self):
        selectors = {m: [r[0] for r in rules(css)] for m, css in self.css.items()}
        self.assertEqual(selectors["dark"], selectors["light"])
        self.assertGreater(len(selectors["dark"]), 40)

    def test_only_token_colors_are_used(self):
        for mode, css in self.css.items():
            p = design.palette(self.tokens, mode)
            allowed = {v.upper() for v in p.values()} | {"#000000"}
            allowed_rgb = {design.hex_to_rgb(v) for v in allowed}
            with self.subTest(mode=mode):
                body = strip_comments(css)
                self.assertLessEqual({c.upper() for c in HEX_IN_CSS.findall(body)}, allowed)
                for r, g, b, _ in RGBA.findall(body):
                    self.assertIn((int(r), int(g), int(b)), allowed_rgb)
                self.assertNotRegex(body, r"\b(white|black)\b", "named colors bypass the tokens")

    def test_opaque_text_on_background_rules_have_contrast(self):
        for mode, css in self.css.items():
            for selectors, decls in rules(css):
                fg, bg = decls.get("color", ""), decls.get("background-color", "")
                if design.HEX.match(fg) and design.HEX.match(bg.replace(" !important", "")):
                    with self.subTest(mode=mode, rule=selectors[0]):
                        self.assertGreaterEqual(design.contrast_ratio(fg, bg.replace(" !important", "")), 4.5)

    def test_focus_ring_is_styled_for_keyboard_users(self):
        for mode, css in self.css.items():
            ring = design.palette(self.tokens, mode)["focus-ring"]
            focus_rules = [(s, d) for s, d in rules(css) if any(":focus" in x for x in s)]
            styled = {x for s, d in focus_rules if ring in d.get("box-shadow", "") for x in s}
            for widget in (".button:focus", ".quick-toggle:focus", ".overview-tile:focus",
                           ".popup-menu-item:focus", ".search-entry:focus", ".list-search-result:focus"):
                with self.subTest(mode=mode, widget=widget):
                    self.assertIn(widget, styled)

    def test_important_only_where_default_theme_needs_it(self):
        allowed = ("#panel", "focus")
        for selectors, decls in rules(self.css["dark"]):
            if any("!important" in v for v in decls.values()):
                with self.subTest(rule=selectors[0]):
                    self.assertTrue(any(a in s for s in selectors for a in allowed), selectors)

    def test_header_declares_supported_shell_versions(self):
        versions = ", ".join(self.platform["gnome_shell"]["supported_versions"])
        for css in self.css.values():
            self.assertIn(f"Target: GNOME Shell {versions}.", css)
            self.assertIn(f"tokens {self.tokens['version']}", css)

    def test_runtime_checks_cover_both_modes(self):
        for mode in design.MODES:
            checks = design.theme_checks(self.tokens, mode)
            self.assertGreaterEqual(len(checks), 10)
            for c in checks:
                self.assertRegex(c["expect"], design.HEX)
                self.assertTrue(c["chain"])

    def test_build_produces_installable_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            design.build(Path(tmp), parts=("extensions",))
            ext = Path(tmp) / "extensions" / design.THEME_UUID
            for name in ("metadata.json", "extension.js", "stylesheet-dark.css", "stylesheet-light.css"):
                self.assertTrue((ext / name).is_file(), name)
            meta = json.loads((ext / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["uuid"], design.THEME_UUID)
            for mode in design.MODES:
                self.assertEqual((ext / f"stylesheet-{mode}.css").read_text(encoding="utf-8"), self.css[mode])
            manifest = json.loads((Path(tmp) / "build-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tokens-version"], self.tokens["version"])

    def test_generated_stylesheets_are_not_in_source(self):
        self.assertFalse(list(design.THEME_EXTENSION.glob("*.css")),
                         "stylesheets are generated into out/, never committed")


if __name__ == "__main__":
    unittest.main()
