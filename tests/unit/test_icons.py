# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX icon theme: structure, inheritance, coverage, colors, rendering."""

import configparser
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import jeronix_design as design  # noqa: E402
import jeronix_icons as icons  # noqa: E402

COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")
REQUIRED = {
    "apps": ["io.jeronix.Launcher", "io.jeronix.LayoutStudio", "io.jeronix.Settings", "io.jeronix.SystemInfo",
             "io.jeronix.Welcome", "org.gnome.Nautilus", "org.gnome.Settings", "org.gnome.Ptyxis",
             "org.gnome.TextEditor", "utilities-terminal", "system-file-manager"],
    "places": ["folder", "folder-documents", "folder-download", "folder-music", "folder-pictures", "folder-videos",
               "user-home", "user-desktop", "user-trash", "user-trash-full"],
    "mimetypes": ["text-x-generic", "image-x-generic", "audio-x-generic", "video-x-generic", "package-x-generic",
                  "application-pdf", "text-x-script", "application-x-executable", "x-office-document"],
}


def renderable():
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        return any(f.get_name() == "svg" for f in GdkPixbuf.Pixbuf.get_formats())
    except (ImportError, ValueError):
        return False


class IconThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = design.load_tokens()
        cls.icons = icons.icons(cls.tokens)

    def test_index_theme_inherits_system_themes(self):
        parser = configparser.ConfigParser()
        parser.read_string(icons.index_theme())
        theme = parser["Icon Theme"]
        self.assertEqual(theme["Name"], "JERONIX")
        self.assertEqual(theme["Inherits"].split(","), ["Yaru", "Adwaita", "hicolor"],
                         "anything not drawn must fall back, so no app shows a missing icon")
        dirs = theme["Directories"].split(",")
        for d in dirs:
            self.assertEqual(parser[d]["Type"], "Scalable")
        files_dirs = {str(Path(rel).parent) for rel in self.icons}
        self.assertEqual(files_dirs, set(dirs))

    def test_required_icons_exist(self):
        for context, names in REQUIRED.items():
            for name in names:
                with self.subTest(icon=f"{context}/{name}"):
                    self.assertIn(f"scalable/{context}/{name}.svg", self.icons)

    def test_icons_are_valid_svg_with_token_colors(self):
        allowed = {v.upper() for v in self.tokens["brand"].values()}
        for mode in self.tokens["color"].values():
            allowed |= {v.upper() for v in mode.values()}
        for rel, text in self.icons.items():
            with self.subTest(icon=rel):
                root = ET.fromstring(text.split("\n", 2)[2])
                self.assertEqual(root.attrib["viewBox"], "0 0 128 128")
                self.assertLessEqual({c.upper() for c in COLOR.findall(text)}, allowed)
                for bad in ("<image", "<script", "<text", "href=\"http"):
                    self.assertNotIn(bad, text)
                self.assertIn("CC-BY-SA-4.0", text)

    def test_consistent_stroke_weight(self):
        widths = set()
        for text in self.icons.values():
            widths |= {float(w) for w in re.findall(r'stroke-width="([\d.]+)"', text)}
        # One main weight plus a lighter detail weight and hairlines/dashes.
        self.assertLessEqual(widths, {2.0, 4.0, 5.0, 6.0, 7.0, 9.0, 11.0})
        self.assertIn(float(icons.STROKE), widths)

    def test_no_third_party_logos(self):
        names = {Path(rel).stem for rel in self.icons}
        for trademark in ("firefox", "ubuntu", "chrome", "thunderbird", "libreoffice", "snap-store"):
            self.assertFalse(any(trademark in n for n in names), trademark)

    def test_build_writes_theme_and_hicolor_app_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = icons.build(self.tokens, Path(tmp))
            theme = Path(tmp) / "icons" / "JERONIX"
            self.assertTrue((theme / "index.theme").is_file())
            for name in REQUIRED["apps"][:5]:
                self.assertTrue((Path(tmp) / "icons" / "hicolor" / "scalable" / "apps" / f"{name}.svg").is_file())
            self.assertEqual(len(built), len(self.icons) + 1 + 5)

    @unittest.skipUnless(renderable(), "gdk-pixbuf SVG loader not available")
    def test_every_icon_renders_at_small_and_large_sizes(self):
        from gi.repository import GdkPixbuf, Gio, GLib
        for rel, text in self.icons.items():
            for size in (16, 256):
                with self.subTest(icon=rel, size=size):
                    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(text.encode()))
                    pb = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, size, size, True, None)
                    self.assertEqual((pb.get_width(), pb.get_height()), (size, size))


if __name__ == "__main__":
    unittest.main()
