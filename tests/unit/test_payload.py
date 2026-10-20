# SPDX-License-Identifier: GPL-3.0-or-later
"""The jeronix-desktop payload and .deb: contents, permissions, defaults
derived from the Pure layout, package metadata, and absence of secrets or
development files."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))


def can_build():
    try:
        from gi.repository import Gio
        return (Gio.SettingsSchemaSource.get_default().lookup("org.gnome.shell.extensions.dash-to-dock", True)
                is not None and shutil.which("dconf") and shutil.which("dpkg-deb"))
    except ImportError:
        return False


class ProfileTests(unittest.TestCase):
    def test_profile_merge(self):
        import jeronix_payload as p
        self.assertEqual(p.dconf_profile(None), "user-db:user\nsystem-db:jeronix\n")
        self.assertEqual(p.dconf_profile("user-db:user\nsystem-db:local\n"),
                         "user-db:user\nsystem-db:local\nsystem-db:jeronix\n")
        self.assertEqual(p.dconf_profile("user-db:user\nsystem-db:jeronix\n"), "user-db:user\nsystem-db:jeronix\n")
        with self.assertRaises(SystemExit):
            p.dconf_profile("system-db:x\n")


@unittest.skipUnless(can_build(), "Ubuntu GNOME schemas, dconf or dpkg-deb missing")
class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jeronix_payload
        cls.p = jeronix_payload
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.deb = jeronix_payload.build_deb(cls.out)
        cls.root = cls.out / "root"
        cls.config = jeronix_payload.load_config()
        cls.files = sorted(str(p.relative_to(cls.root)) for p in cls.root.rglob("*") if p.is_file())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_expected_files(self):
        for rel in ("usr/share/gnome-shell/extensions/jeronix-shell-theme@jeronix/stylesheet-dark.css",
                    "usr/share/gnome-shell/extensions/jeronix-shell-theme@jeronix/stylesheet-light.css",
                    "usr/share/gnome-shell/extensions/jeronix-quick-settings@jeronix/inhibitor.js",
                    "usr/share/backgrounds/jeronix/jeronix-dark.png",
                    "usr/share/backgrounds/jeronix/jeronix-light.png",
                    "usr/share/gnome-background-properties/jeronix.xml",
                    "usr/share/icons/hicolor/256x256/apps/jeronix.png",
                    "usr/share/icons/hicolor/symbolic/apps/jeronix-symbolic.svg",
                    "usr/share/jeronix/layouts/pure.json", "usr/bin/jeronix-layout",
                    "etc/dconf/profile/user", "etc/dconf/db/jeronix", "etc/dconf/db/jeronix.d/00-jeronix",
                    "etc/jeronix-release", "usr/share/doc/jeronix-desktop/copyright"):
            self.assertIn(rel, self.files)

    def test_installer_branding_and_first_login(self):
        self.assertIn("usr/share/desktop-provision/whitelabel.yaml", self.files)
        self.assertIn("usr/share/desktop-provision/slides/1/slide_en_US.html", self.files)
        self.assertEqual((self.root / "etc/skel/.config/gnome-initial-setup-done").read_text(), "yes\n",
                         "new users go straight to JERONIX Welcome")
        dropin = (self.root / "etc/systemd/user/ubuntu-desktop-installer.service.d/jeronix.conf").read_text()
        self.assertIn("[Service]\nExecStopPost=\n", dropin, "the installer no longer brings Ubuntu's icons back")

    def test_only_expected_top_level_trees(self):
        allowed = ("etc/dconf/", "etc/jeronix-release", "usr/bin/jeronix-layout", "usr/share/gnome-shell/extensions/",
                   "usr/share/backgrounds/jeronix/", "usr/share/gnome-background-properties/jeronix.xml",
                   "usr/share/icons/hicolor/", "usr/share/icons/JERONIX/", "usr/share/jeronix/",
                   "usr/share/desktop-provision/", "etc/skel/.config/gnome-initial-setup-done",
                   "etc/systemd/user/ubuntu-desktop-installer.service.d/jeronix.conf",
                   "usr/share/doc/jeronix-desktop/", "usr/share/applications/io.jeronix.",
                   "etc/xdg/autostart/io.jeronix.Welcome.desktop", "etc/xdg/autostart/io.jeronix.UserSetup.desktop",
                   "etc/xdg/fastfetch/config.jsonc", "usr/share/gdm/dconf/95-jeronix-settings",
                   "usr/share/glib-2.0/schemas/90_jeronix.gschema.override", "usr/share/plymouth/themes/jeronix/",
                   "usr/share/plymouth/themes/jeronix-text/")
        for rel in self.files:
            self.assertTrue(rel.startswith(allowed), rel)

    def test_no_secrets_or_development_files(self):
        for rel in self.files:
            with self.subTest(file=rel):
                self.assertNotRegex(rel, r"(__pycache__|\.pyc$|\.git|/tests?/|\.pf$|\.log$|~$)")
                data = (self.root / rel).read_bytes()
                for marker in (b"PRIVATE KEY", b"BEGIN OPENSSH", b"/home/", b"jeronix-test-probe"):
                    self.assertNotIn(marker, data)
                # A password with a literal value is a secret; the word alone
                # is not (JERONIX Settings asks for Wi-Fi passwords).
                self.assertNotRegex(data, rb"(?i)(password|passwd|psk)[\"']?\s*[=:]\s*[\"'][^\"']+[\"']")

    def test_permissions(self):
        for p in self.root.rglob("*"):
            mode = p.stat().st_mode & 0o7777
            with self.subTest(path=str(p.relative_to(self.root))):
                self.assertFalse(mode & 0o022, "nothing group/world-writable")
                if p.is_file() and mode & 0o111:
                    self.assertEqual(str(p.relative_to(self.root)), "usr/bin/jeronix-layout")

    def test_dconf_defaults_follow_pure_layout(self):
        keyfile = (self.root / "etc/dconf/db/jeronix.d/00-jeronix").read_text()
        pure = json.loads((ROOT / "desktop/layouts/pure.json").read_text())
        for s in pure["settings"]:
            self.assertRegex(keyfile, rf"(?m)^{re.escape(s['key'])}=", s["key"])
        self.assertIn("file:///usr/share/backgrounds/jeronix/jeronix-dark.png", keyfile)
        self.assertNotIn(".local/share", keyfile)
        exts = ", ".join(f"'{e}'" for e in self.p.default_extensions())
        self.assertIn(f"enabled-extensions=[{exts}]", keyfile)
        self.assertIn("disabled-extensions=['ubuntu-dock@ubuntu.com', 'ding@rastersoft.com']", keyfile)
        self.assertIn("[org/gnome/shell/extensions/jeronix-dock]", keyfile)
        db = (self.root / "etc/dconf/db/jeronix").read_bytes()
        self.assertTrue(db.startswith(b"GVariant"), "compiled dconf database")

    def test_enabled_extensions_are_shipped_and_supported(self):
        platform = json.loads((ROOT / "config/platform.json").read_text())
        for uuid in self.p.default_extensions():
            meta = json.loads((self.root / f"usr/share/gnome-shell/extensions/{uuid}/metadata.json").read_text())
            self.assertEqual(meta["uuid"], uuid)
            self.assertEqual(meta["shell-version"], platform["gnome_shell"]["supported_versions"])

    def test_background_properties_point_at_shipped_files(self):
        wp = ET.parse(self.root / "usr/share/gnome-background-properties/jeronix.xml").find("wallpaper")
        for tag in ("filename", "filename-dark"):
            self.assertTrue((self.root / wp.find(tag).text.lstrip("/")).is_file())

    def test_deb_metadata(self):
        info = subprocess.run(["dpkg-deb", "-f", self.deb], capture_output=True, text=True, check=True).stdout
        self.assertIn(f"Package: {self.config['package']}", info)
        self.assertIn("Architecture: all", info)
        major = json.loads((ROOT / "config/platform.json").read_text())["gnome_shell"]["supported_versions"][0]
        self.assertIn(f"gnome-shell (>= {major})", info)
        self.assertIn(f"gnome-shell (<< {int(major) + 1})", info)
        contents = subprocess.run(["dpkg-deb", "-c", self.deb], capture_output=True, text=True, check=True).stdout
        owners = {l.split()[1] for l in contents.splitlines()}
        self.assertEqual(owners, {"root/root"})
        conffiles = subprocess.run(["dpkg-deb", "-I", self.deb, "conffiles"], capture_output=True, text=True,
                                   check=True).stdout.split()
        # The .deb also carries the replacements for diverted Ubuntu files,
        # which the ISO layer (self.files) must never contain.
        replaced = {p.lstrip("/") for p in self.p.REPLACED}
        self.assertFalse(replaced & set(self.files), "replacements stay out of the ISO layer")
        self.assertEqual(sorted(conffiles), sorted("/" + f for f in set(self.files) | replaced if f.startswith("etc/")))
        listed = {l.split()[-1].lstrip("./") for l in contents.splitlines() if not l.startswith("d")}
        self.assertEqual(listed, set(self.files) | replaced)

    def test_maintainer_scripts(self):
        scripts = self.p.maintainer_scripts()
        self.assertEqual(sorted(scripts), ["postinst", "postrm", "preinst", "prerm", "triggers"])
        for name in ("preinst", "postrm"):
            self.assertIn(" ".join(self.p.DIVERSIONS), scripts[name])
            self.assertNotIn("@DIVERSIONS@", scripts[name])
        self.assertIn('--divert "$path.ubuntu"', scripts["preinst"])
        self.assertIn("--remove --rename", scripts["postrm"])
        # Optional steps never fail the installation.
        for command in ("update-initramfs -u", "update-grub", "gdm-theme.gresource \"$GREETER\" 50"):
            line = next(l for l in scripts["postinst"].splitlines() if command in l)
            self.assertTrue("||" in line or line.rstrip().endswith("\\") or "if " in line, line)
        for name in ("preinst", "postinst", "prerm", "postrm"):
            result = subprocess.run(["sh", "-n"], input=scripts[name], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr}")

    def test_identity_keeps_machine_ids(self):
        platform = json.loads((ROOT / "config/platform.json").read_text())
        files = self.p.os_identity(self.p.load_config(), platform)
        os_release = files["usr/lib/os-release"]
        self.assertIn('NAME="JERONIX"', os_release)
        self.assertIn('PRETTY_NAME="JERONIX', os_release)
        self.assertIn("ID=ubuntu", os_release, "apt and Ubuntu tooling depend on it")
        self.assertIn(f"UBUNTU_CODENAME={platform['ubuntu']['codename']}", os_release)
        self.assertNotIn("Ubuntu", os_release.replace("UBUNTU_CODENAME", ""), "no Ubuntu in the names people see")
        self.assertIn("DISTRIB_ID=Ubuntu", files["etc/lsb-release"])
        self.assertIn('DISTRIB_DESCRIPTION="JERONIX', files["etc/lsb-release"])
        self.assertTrue(files["etc/issue"].startswith("JERONIX"))

    def test_layout_tool_runs_from_installed_location(self):
        tool = self.root / "usr/share/jeronix/scripts/jeronix_layout.py"
        # On an installed system the extensions are in /usr/share; here they
        # are in the payload tree.
        env = dict(os.environ, JERONIX_EXTENSION_DIRS=str(self.root / "usr/share/gnome-shell/extensions"))
        for layout in sorted((self.root / "usr/share/jeronix/layouts").glob("*.json")):
            result = subprocess.run([sys.executable, tool, "validate", layout], capture_output=True, text=True,
                                    env=env)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
