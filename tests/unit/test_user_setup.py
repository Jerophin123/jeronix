# SPDX-License-Identifier: GPL-3.0-or-later
"""The JERONIX per-user setup (scripts/jeronix_user_setup.py) in a temporary
home folder, and the generated desktop files it installs (GTK colors and
the terminal palette, from scripts/jeronix_design.py)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps"))

import jeronix_design as design  # noqa: E402
import jeronix_user_setup as setup  # noqa: E402
from jeronix_common import style  # noqa: E402

BASHRC = "# ~/.bashrc: executed by bash(1) for non-login shells.\nalias ll='ls -alF'\n"


class UserSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.data = base / "data"
        (self.data / "terminal").mkdir(parents=True)
        (self.data / "gtk").mkdir()
        for name in ("prompt.sh", "fastfetch-logo.txt", "fastfetch.jsonc.in"):
            (self.data / "terminal" / name).write_bytes((ROOT / "desktop" / "terminal" / name).read_bytes())
        tokens = design.load_tokens()
        (self.data / "gtk" / "gtk-4.0.css").write_text(design.gtk4_css(tokens), encoding="utf-8")
        (self.data / "terminal" / "JERONIX.palette").write_text(design.ptyxis_palette(tokens), encoding="utf-8")
        (self.home / ".bashrc").write_text(BASHRC, encoding="utf-8")
        env = {"XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.home / ".local/share"),
               "XDG_STATE_HOME": str(self.home / ".local/state")}
        self.patches = [mock.patch.dict(os.environ, env), mock.patch.object(setup, "home", lambda: self.home),
                        mock.patch.object(setup, "gsettings", lambda *a: None)]  # no Ptyxis here
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def run_setup(self, *args):
        with mock.patch("sys.stdout"):
            return setup.main(["--data", str(self.data), *args])

    def read(self, rel):
        return (self.home / rel).read_text(encoding="utf-8")

    def test_apply(self):
        self.assertEqual(self.run_setup(), 0)
        gtk = self.read(".config/gtk-4.0/gtk.css")
        self.assertTrue(gtk.startswith('@import url("file://'), "the import comes first")
        self.assertIn("gtk-4.0.css", gtk)
        bashrc = self.read(".bashrc")
        self.assertTrue(bashrc.startswith(BASHRC.rstrip()), "the user's own lines are kept")
        self.assertEqual(bashrc.count(setup.BASH_BEGIN), 1)
        self.assertIn("prompt.sh", bashrc)
        fastfetch = self.read(".config/fastfetch/config.jsonc")
        self.assertIn(str((self.data / "terminal" / "fastfetch-logo.txt").resolve()), fastfetch)
        self.assertNotIn("@LOGO@", fastfetch)
        self.assertTrue((self.home / ".local/share/org.gnome.Ptyxis/palettes/JERONIX.palette").is_file())

    def test_applied_once_then_respects_the_user(self):
        self.run_setup()
        (self.home / ".bashrc").write_text(BASHRC, encoding="utf-8")  # the user removed the block
        self.run_setup()
        self.assertNotIn(setup.BASH_BEGIN, self.read(".bashrc"), "a removed block stays removed")
        self.run_setup("--force")
        self.assertEqual(self.read(".bashrc").count(setup.BASH_BEGIN), 1, "--force applies it once again")
        self.run_setup("--force")
        self.assertEqual(self.read(".bashrc").count(setup.BASH_BEGIN), 1, "never twice")
        self.assertEqual(self.read(".config/gtk-4.0/gtk.css").count(setup.GTK_MARK), 1)

    def test_own_files_are_kept(self):
        gtk = self.home / ".config/gtk-4.0/gtk.css"
        gtk.parent.mkdir(parents=True)
        gtk.write_text("window { border-radius: 0; }\n", encoding="utf-8")
        ff = self.home / ".config/fastfetch/config.jsonc"
        ff.parent.mkdir(parents=True)
        ff.write_text('{"modules": ["os"]}\n', encoding="utf-8")
        self.run_setup()
        self.assertIn("window { border-radius: 0; }", self.read(".config/gtk-4.0/gtk.css"))
        self.assertEqual(self.read(".config/fastfetch/config.jsonc"), '{"modules": ["os"]}\n',
                         "someone's own fastfetch configuration is never replaced")

    def test_undo_restores(self):
        gtk = self.home / ".config/gtk-4.0/gtk.css"
        gtk.parent.mkdir(parents=True)
        gtk.write_text("window { border-radius: 0; }\n", encoding="utf-8")
        self.run_setup()
        self.run_setup("--undo")
        self.assertEqual(self.read(".config/gtk-4.0/gtk.css"), "window { border-radius: 0; }\n")
        self.assertEqual(self.read(".bashrc").rstrip(), BASHRC.rstrip())
        self.assertFalse((self.home / ".config/fastfetch/config.jsonc").exists())
        self.assertFalse((self.home / ".local/share/org.gnome.Ptyxis/palettes/JERONIX.palette").exists())
        self.assertFalse(setup.stamp().exists())

    def test_snap_icons(self):
        snaps = Path(self.tmp.name) / "snapd"
        snaps.mkdir()
        entry = snaps / "snap-store_snap-store.desktop"
        entry.write_text("[Desktop Entry]\nName=App Center\nExec=/snap/bin/snap-store %U\n"
                         "Icon=/snap/snap-store/current/app-center.png\nTryExec=/snap/bin/snap-store\n",
                         encoding="utf-8")
        setup.snap_icons_apply(snaps)
        ours = self.home / ".local/share/applications/snap-store_snap-store.desktop"
        text = ours.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(setup.SNAP_MARK))
        self.assertIn("Icon=jeronix-app-center", text)
        self.assertIn("Exec=/snap/bin/snap-store %U", text, "everything else is the snap's own")
        self.assertNotIn("app-center.png", text)
        # Someone's own entry is never touched.
        own = self.home / ".local/share/applications/desktop-security-center_desktop-security-center.desktop"
        own.write_text("[Desktop Entry]\nName=Mine\n", encoding="utf-8")
        (snaps / own.name).write_text("[Desktop Entry]\nIcon=/snap/x.png\n", encoding="utf-8")
        setup.snap_icons_apply(snaps)
        self.assertEqual(own.read_text(encoding="utf-8"), "[Desktop Entry]\nName=Mine\n")
        # The snap goes away: so does our copy.
        entry.unlink()
        setup.snap_icons_apply(snaps)
        self.assertFalse(ours.exists())
        setup.snap_icons_apply(snaps)
        entry.write_text("[Desktop Entry]\nIcon=/snap/y.png\n", encoding="utf-8")
        setup.snap_icons_apply(snaps)
        setup.snap_icons_undo()
        self.assertFalse(ours.exists())
        self.assertTrue(own.exists())

    def test_missing_data_is_reported(self):
        with mock.patch("sys.stdout"):
            self.assertEqual(setup.main(["--data", str(self.home / "nowhere")]), 1)


class GeneratedDesktopFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = design.load_tokens()

    def test_gtk_colors_cover_both_modes_and_spare_high_contrast(self):
        css = design.gtk4_css(self.tokens)
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertEqual(css.count("prefers-contrast: no-preference"), 2)
        for mode in ("dark", "light"):
            p = design.palette(self.tokens, mode)
            self.assertNotIn("--accent", css, "the accent chosen in Settings must win")
            self.assertIn(f"--window-bg-color: {p['surface']};", css)

    def test_gtk_colors_agree_with_the_jeronix_apps(self):
        # The apps style themselves with the same variables (style.css_for).
        for mode in ("dark", "light"):
            app_css = style.css_for(self.tokens, mode)
            p = design.palette(self.tokens, mode)
            for name, role in design.GTK_COLORS.items():
                if f"--{name}:" in app_css:
                    with self.subTest(mode=mode, variable=name):
                        self.assertIn(f"--{name}: {p[role]};", app_css)

    def test_terminal_palette(self):
        text = design.ptyxis_palette(self.tokens)
        for section in ("[Palette]", "Name=JERONIX", "[Light]", "[Dark]", "Color15="):
            self.assertIn(section, text)
        for mode, role in design.TERMINAL_BACKGROUND.items():
            background = design.palette(self.tokens, mode)[role]
            self.assertEqual(len(design.TERMINAL_ANSI[mode]), 16)
            for i in design.TERMINAL_COLORED:
                with self.subTest(mode=mode, color=i):
                    self.assertGreaterEqual(design.contrast_ratio(design.TERMINAL_ANSI[mode][i], background), 4.5)


if __name__ == "__main__":
    unittest.main()
