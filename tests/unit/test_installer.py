# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX branding for Ubuntu's installer (packaging/jeronix_installer.py):
the whitelabel config only names pages the installer has and images that
exist, the pictures are clean SVG, and the slides are complete."""

import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))

import jeronix_installer as installer  # noqa: E402

# The installer's page names (its own whitelabel.yml in ubuntu-desktop-bootstrap 26.04.1).
INSTALLER_PAGES = {
    "locale", "accessibility", "try-or-install", "rst", "keyboard", "network", "refresh", "autoinstall",
    "autoinstall-direct", "autoinstall-landscape-domain", "autoinstall-landscape-qr", "autoinstall-landscape-error",
    "source-selection", "codecs-and-drivers", "not-enough-disk-space", "secure-boot", "bitlocker", "storage",
    "guided-capabilities", "tpm-action", "eula", "guided-resize", "guided-reformat", "passphrase-type", "passphrase",
    "recovery-key", "confirm", "identity", "active-directory", "ubuntu-pro-onboarding", "ubuntu-pro",
    "ubuntu-pro-success", "privacy", "timezone", "telemetry", "welcome", "done", "storage-icon", "error",
}


class InstallerBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.files = installer.build(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def config(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not available")
        return yaml.safe_load((self.out / "whitelabel.yaml").read_text(encoding="utf-8"))

    def test_whitelabel_names_real_pages_and_images(self):
        config = self.config()
        self.assertEqual(config["app-name"], "JERONIX Installer")
        for mode in ("light", "dark"):
            for key in ("accent-color", "elevated-button-color", "elevated-button-text-color"):
                self.assertRegex(config["theme"][mode][key], r"^#[0-9A-F]{6}$")
        self.assertLessEqual(set(config["pages"]), INSTALLER_PAGES)
        for page in ("locale", "try-or-install", "keyboard", "storage", "identity", "done"):
            self.assertIn(page, config["pages"])
        for page, entry in config["pages"].items():
            for key in ("image", "image-dark"):
                if key in entry:
                    with self.subTest(page=page, key=key):
                        self.assertFalse(entry[key].startswith("assets/"), "a JERONIX picture, by name")
                        self.assertTrue((self.out / "images" / entry[key]).is_file())

    def test_pictures_are_clean_svg(self):
        for path in self.out.rglob("*.svg"):
            with self.subTest(svg=path.name):
                text = path.read_text(encoding="utf-8")
                root = ET.fromstring(text)
                self.assertTrue(root.tag.endswith("svg"))
                for bad in ("<script", "<image", "href=\"http", "@import"):
                    self.assertNotIn(bad, text)

    def test_slides_are_complete(self):
        slides = sorted((self.out / "slides").iterdir(), key=lambda p: int(p.name))
        self.assertEqual([p.name for p in slides], [str(n) for n in range(1, len(installer.SLIDES) + 1)])
        for slide in slides:
            with self.subTest(slide=slide.name):
                html = (slide / "slide_en_US.html").read_text(encoding="utf-8")
                pictures = re.findall(r'src="([^"]+)"', html)
                self.assertTrue(pictures)
                for picture in pictures:
                    self.assertTrue((slide / picture).is_file(), picture)
                self.assertNotIn("Ubuntu Pro", html)
                self.assertNotRegex(html, r"<script|javascript:")
        first = (slides[0] / "slide_en_US.html").read_text(encoding="utf-8")
        self.assertIn("{{ DISTRO }}", first, "the installer puts the product name in")


if __name__ == "__main__":
    unittest.main()
