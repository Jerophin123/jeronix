# SPDX-License-Identifier: GPL-3.0-or-later
"""Logo, icon and wallpaper checks: SVG validity, token colors, rendering."""

import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_design as design  # noqa: E402

ICONS = ROOT / "design" / "icons"
# Vendored third-party icons (MIT, see its README), checked in test_icons.py.
THIRD_PARTY = "fluent"
SVG_NS = "{http://www.w3.org/2000/svg}"
REQUIRED = {
    "jeronix-mark.svg": (128, 128),
    "jeronix-mark-small.svg": (16, 16),
    "jeronix-mark-symbolic.svg": (16, 16),
    "jeronix-glyph-on-dark.svg": (128, 128),
    "jeronix-glyph-on-light.svg": (128, 128),
    "jeronix-wordmark-on-dark.svg": (242, 56),
    "jeronix-wordmark-on-light.svg": (242, 56),
    "jeronix-lockup-on-dark.svg": (424, 128),
    "jeronix-lockup-on-light.svg": (424, 128),
    "jeronix-boot.svg": (256, 184),
}
COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")


def token_colors(tokens):
    colors = {v.upper() for v in tokens["brand"].values()}
    for mode in tokens["color"].values():
        colors |= {v.upper() for v in mode.values()}
    return colors


def can_render():
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        return any(f.get_name() == "svg" for f in GdkPixbuf.Pixbuf.get_formats())
    except (ImportError, ValueError):
        return False


def alpha_coverage(png):
    """Fraction of non-transparent pixels in a rendered PNG."""
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(str(png))
    if not pb.get_has_alpha():
        return 1.0
    data, stride, n = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
    opaque = sum(1 for y in range(pb.get_height()) for x in range(pb.get_width())
                 if data[y * stride + x * n + 3] > 0)
    return opaque / (pb.get_width() * pb.get_height())


class LogoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = design.load_tokens()

    def test_required_assets_exist(self):
        for name in REQUIRED:
            self.assertTrue((ICONS / name).is_file(), name)

    def test_previous_logo_is_preserved(self):
        self.assertTrue((ICONS / "archive" / "jeronix-mark-v0.1.svg").is_file())

    def test_svgs_are_clean_and_self_contained(self):
        for svg in sorted(ICONS.rglob("*.svg")):
            with self.subTest(svg=svg.name):
                text = svg.read_text(encoding="utf-8")
                root = ET.fromstring(text)
                self.assertEqual(root.tag, f"{SVG_NS}svg")
                self.assertIn("viewBox", root.attrib)
                if THIRD_PARTY not in svg.relative_to(ICONS).parts:
                    self.assertIn("SPDX-License-Identifier: CC-BY-SA-4.0", text)
                for bad in ("<image", "<script", "<text", "<style", "href=", "@import", "font-family"):
                    self.assertNotIn(bad, text, "assets must not depend on fonts, scripts or files")

    def test_dimensions_match_viewbox(self):
        for name, (w, h) in REQUIRED.items():
            with self.subTest(svg=name):
                root = ET.parse(ICONS / name).getroot()
                vb = [float(v) for v in root.attrib["viewBox"].split()]
                self.assertEqual((float(root.attrib["width"]), float(root.attrib["height"])), (w, h))
                self.assertEqual((vb[2], vb[3]), (w, h))

    def test_brand_artwork_uses_token_colors(self):
        allowed = token_colors(self.tokens)
        # design/icons/archive keeps retired artwork in its original palette.
        for svg in sorted(p for p in ICONS.rglob("*.svg")
                          if not {"archive", THIRD_PARTY} & set(p.relative_to(ICONS).parts)):
            with self.subTest(svg=svg.name):
                used = {c.upper() for c in COLOR.findall(svg.read_text(encoding="utf-8"))}
                self.assertLessEqual(used, allowed, f"colors not in tokens: {used - allowed}")

    def test_symbolic_icon_uses_fills_only(self):
        # GTK recolors symbolic icons by filling every shape, so strokes or
        # fill="none" would render as solid blobs.
        text = (ICONS / "jeronix-mark-symbolic.svg").read_text(encoding="utf-8")
        self.assertNotIn("stroke", text)
        self.assertNotIn('fill="none"', text)

    def test_variants_share_the_same_glyph(self):
        def j_path(name):
            root = ET.parse(ICONS / name).getroot()
            return [p.attrib["d"] for p in root.iter(f"{SVG_NS}path") if p.attrib["d"].startswith("M78.5")]
        reference = j_path("jeronix-mark.svg")
        self.assertEqual(len(reference), 1)
        for name in ("jeronix-glyph-on-dark.svg", "jeronix-glyph-on-light.svg", "jeronix-lockup-on-dark.svg",
                     "jeronix-lockup-on-light.svg", "jeronix-boot.svg"):
            with self.subTest(svg=name):
                self.assertEqual(j_path(name), reference)

    @unittest.skipUnless(can_render(), "gdk-pixbuf SVG loader not available")
    def test_icons_render_at_every_token_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = design.build_icons(self.tokens, Path(tmp))
            for size in self.tokens["icon-size-px"]:
                png = Path(tmp) / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "jeronix.png"
                with self.subTest(size=size):
                    self.assertIn(png, built)
                    # The rounded tile should cover most of the canvas at every size.
                    self.assertGreater(alpha_coverage(png), 0.6)


class WallpaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = design.load_tokens()

    def test_wallpapers_are_valid_and_use_brand_colors(self):
        brand = {v.upper() for v in self.tokens["brand"].values()}
        for mode in design.MODES:
            for w, h in design.WALLPAPER_SIZES:
                with self.subTest(mode=mode, size=f"{w}x{h}"):
                    svg = design.wallpaper_svg(self.tokens, mode, w, h)
                    root = ET.fromstring(svg)
                    self.assertEqual(root.attrib["viewBox"], f"0 0 {w} {h}")
                    self.assertLessEqual({c.upper() for c in COLOR.findall(svg)}, brand)

    def test_composition_stays_on_canvas(self):
        # The contours may leave through the top edge only.
        number = re.compile(r"-?\d+(?:\.\d+)?")
        for mode in design.MODES:
            for w, h in design.WALLPAPER_SIZES:
                root = ET.fromstring(design.wallpaper_svg(self.tokens, mode, w, h))
                for path in root.iter(f"{SVG_NS}path"):
                    d = path.attrib["d"]
                    xs = [float(v) for v in number.findall(d.split("V")[0][1:])][:1]
                    with self.subTest(mode=mode, size=f"{w}x{h}"):
                        self.assertTrue(all(0 < x < w for x in xs), d)

    def test_modes_differ(self):
        self.assertNotEqual(design.wallpaper_svg(self.tokens, "dark", 1920, 1080),
                            design.wallpaper_svg(self.tokens, "light", 1920, 1080))

    @unittest.skipUnless(can_render(), "gdk-pixbuf SVG loader not available")
    def test_wallpapers_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = design.build_wallpapers(self.tokens, Path(tmp), sizes=((1920, 1080), (2560, 1600)))
            names = {p.name for p in built}
            for mode in design.MODES:
                self.assertIn(f"jeronix-{mode}.svg", names)
                for size in ("1920x1080", "2560x1600"):
                    png = Path(tmp) / "wallpapers" / f"jeronix-{mode}-{size}.png"
                    self.assertTrue(png.is_file())
                    self.assertLess(png.stat().st_size, 2_000_000, "wallpapers must stay small")


if __name__ == "__main__":
    unittest.main()
