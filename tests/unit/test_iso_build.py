# SPDX-License-Identifier: GPL-3.0-or-later
"""ISO builder: configuration, checksum and signature verification, ISO
metadata edits, base-layer rebuild, failure handling. No Ubuntu ISO is
needed; the squashfs tests use small synthetic images."""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "build" / "iso"))
import jeronix_iso as iso  # noqa: E402
from isoread import IsoImage  # noqa: E402

logging.getLogger("jeronix-iso").addHandler(logging.NullHandler())
logging.getLogger("jeronix-iso").propagate = False

FPR = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
GRUB_CFG = '''set timeout=30

menuentry "Try or Install Ubuntu" {
    linux  /casper/vmlinuz  --- quiet splash
    initrd /casper/initrd
}
menuentry "Ubuntu (safe graphics)" {
    linux  /casper/vmlinuz nomodeset  --- quiet splash
    initrd /casper/initrd
}
'''
SOURCES = '''sources:
- default: true
  description:
    en: A minimal but usable Ubuntu Desktop.
  name:
    en: Ubuntu Desktop (minimized)
  path: minimal.squashfs
  size: 6506545152
  variations:
    minimal:
      path: minimal.squashfs
      size: 3436847104
- default: false
  name:
    en: Ubuntu Desktop
  path: minimal.standard.squashfs
  size: 8270364672
version: 2
'''


def have(*tools):
    return all(shutil.which(t) for t in tools)


class ConfigTests(unittest.TestCase):
    def test_base_config_is_valid(self):
        base = iso.load_base()
        self.assertEqual(base["signing_key"]["fingerprint"], FPR)
        self.assertTrue(base["mirror"].startswith("https://releases.ubuntu.com/"))
        self.assertEqual(base["output"]["name"], "jeronix-26.04-x86_64.iso")

    def test_base_matches_platform(self):
        platform = json.loads((ROOT / "config" / "platform.json").read_text())
        base = iso.load_base()
        self.assertEqual(base["ubuntu"]["series"], platform["ubuntu"]["version"])
        self.assertEqual(base["ubuntu"]["codename"], platform["ubuntu"]["codename"])
        self.assertIn(base["ubuntu"]["arch"], platform["architectures"])

    def test_untrusted_mirror_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = json.loads(iso.BASE.read_text())
            bad["mirror"] = "http://example.com/ubuntu/"
            path = Path(tmp) / "base.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(iso.BuildError):
                iso.load_base(path)

    @unittest.skipUnless(Path("/usr/share/keyrings/ubuntu-archive-keyring.gpg").exists() and have("gpg"),
                         "ubuntu-keyring not installed")
    def test_pinned_key_is_in_system_keyring(self):
        out = subprocess.run(["gpg", "--no-default-keyring", "--keyring",
                              "/usr/share/keyrings/ubuntu-archive-keyring.gpg", "--with-colons",
                              "--list-keys"], capture_output=True, text=True).stdout
        self.assertIn(f"fpr:::::::::{FPR}:", out)


class VerificationTests(unittest.TestCase):
    def test_signature_requires_validsig_from_pinned_key(self):
        ok = f"[GNUPG:] GOODSIG D94AA3F0EFE21092 Ubuntu\n[GNUPG:] VALIDSIG {FPR} 2026-08-27 x\n"
        iso.check_signature_status(ok, FPR)
        for bad in (
            "[GNUPG:] GOODSIG D94AA3F0EFE21092 Ubuntu\n",  # no VALIDSIG
            f"[GNUPG:] VALIDSIG {'A' * 40} 2026 x\n",  # someone else's key
            f"[GNUPG:] BADSIG D94AA3F0EFE21092 Ubuntu\n[GNUPG:] VALIDSIG {FPR} x\n",
            "[GNUPG:] ERRSIG D94AA3F0EFE21092 1 10 00 1 9\n[GNUPG:] NO_PUBKEY D94AA3F0EFE21092\n",
            f"[GNUPG:] EXPKEYSIG D94AA3F0EFE21092 x\n[GNUPG:] VALIDSIG {FPR} x\n",
        ):
            with self.subTest(status=bad.splitlines()[0]):
                with self.assertRaises(iso.BuildError):
                    iso.check_signature_status(bad, FPR)

    def test_expected_checksum_parsing(self):
        a, b = "a" * 64, "b" * 64
        sums = f"{a} *ubuntu-26.04.1-desktop-amd64.iso\n{b} *ubuntu-26.04.1-desktop-amd64.iso.zsync\n"
        self.assertEqual(iso.expected_checksum(sums, "ubuntu-26.04.1-desktop-amd64.iso"), a)
        self.assertEqual(iso.expected_checksum(f"{a}  x.iso\n", "x.iso"), a)
        with self.assertRaises(iso.BuildError):
            iso.expected_checksum(sums, "other.iso")
        with self.assertRaises(iso.BuildError):
            iso.expected_checksum(f"{a} *x.iso\n{b} *x.iso\n", "x.iso")

    def test_iso_hash_mismatch_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.iso"
            f.write_bytes(b"not ubuntu")
            good = iso.sha256(f)
            self.assertEqual(iso.verify_iso(f, f"{good} *x.iso\n", "x.iso"), good)
            with self.assertRaises(iso.BuildError):
                iso.verify_iso(f, f"{'0' * 64} *x.iso\n", "x.iso")

    @unittest.skipUnless(have("gpgv"), "gpgv not installed")
    def test_forged_checksum_file_is_rejected(self):
        base = iso.load_base()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / base["checksums"]).write_text(f"{'0' * 64} *{base['iso']}\n")
            (cache / base["signature"]).write_bytes(b"-----BEGIN PGP SIGNATURE-----\nforged\n")
            (cache / base["iso"]).write_bytes(b"fake")
            with self.assertRaises(iso.BuildError):
                iso.obtain_source(base, cache, offline=True)
            self.assertTrue((cache / base["iso"]).exists(), "unverified sums never touch the ISO")

    def test_offline_without_cache_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(iso.BuildError, "--offline"):
                iso.obtain_source(iso.load_base(), Path(tmp), offline=True)


class MetadataEditTests(unittest.TestCase):
    def test_grub_titles(self):
        out = iso.edit_grub_cfg(GRUB_CFG)
        self.assertIn('menuentry "Try or Install JERONIX"', out)
        self.assertIn('menuentry "JERONIX (safe graphics)"', out)
        self.assertNotIn("Ubuntu", out)
        # Kernel command lines are untouched.
        self.assertEqual([l for l in out.splitlines() if "linux" in l],
                         [l for l in GRUB_CFG.splitlines() if "linux" in l])
        with self.assertRaises(iso.BuildError):
            iso.edit_grub_cfg("menuentry \"Something else\" {}\n")

    def test_install_sources(self):
        out = iso.edit_install_sources(SOURCES, 1000)
        self.assertIn("size: 6506546152", out)
        self.assertIn("size: 3436848104", out)
        self.assertIn("size: 8270365672", out)
        self.assertIn("en: JERONIX Desktop (minimized, Ubuntu base)", out)
        self.assertIn("en: JERONIX Desktop (Ubuntu base)", out)
        self.assertIn("path: minimal.squashfs", out)
        self.assertIn("en: A minimal but usable Ubuntu Desktop.", out, "descriptions are left alone")
        with self.assertRaises(iso.BuildError):
            iso.edit_install_sources(SOURCES.replace("Ubuntu Desktop (minimized)", "X"), 1)
        try:
            import yaml
        except ImportError:
            return
        self.assertEqual(len(yaml.safe_load(out)["sources"]), 2)

    def test_boot_report_parsing(self):
        # Captured from ubuntu-26.04.1-desktop-amd64.iso with xorriso 1.5.6.
        el_torito = ("El Torito boot img :   1  BIOS  y   none  0x0000  0x00      4         673\n"
                     "El Torito boot img :   2  UEFI  y   none  0x0000  0x00  10296     3162499\n")
        system_area = ("System area summary: MBR protective-msdos-label grub2-mbr cyl-align-off GPT\n"
                       "GPT type GUID      :   1  a2a0d0ebe5b9334487c068b6b72699c7\n"
                       "GPT start and size :   1  64  12649932\n"
                       "GPT type GUID      :   2  28732ac11ff8d211ba4b00a0c93ec93b\n"
                       "GPT start and size :   2  12649996  10296\n")
        self.assertEqual(iso.efi_partition(system_area), (12649996, 10296))
        self.assertEqual(iso.boot_summary((el_torito, system_area)),
                         {"bios_el_torito": True, "uefi_el_torito": True, "gpt": True, "mbr": True,
                          "efi_partition": True})
        self.assertFalse(iso.boot_summary((el_torito.splitlines()[0], "MBR only"))["uefi_el_torito"])
        self.assertIsNone(iso.efi_partition("GPT type GUID      :   1  a2a0d0ebe5b9334487c068b6b72699c7\n"))

    def test_eltorito_comparison_ignores_only_boot_info_fields(self):
        a = bytes(4096)
        patched = bytearray(a)
        patched[8:64] = b"\x01" * 56
        patched[2548:2556] = b"\x02" * 8
        self.assertEqual(iso.unpatched_differences(a, bytes(patched)), [])
        patched[100] = 7
        self.assertEqual(iso.unpatched_differences(a, bytes(patched)), [100])
        self.assertEqual(iso.unpatched_differences(a, a + b"x"), ["length"])
        report = "El Torito boot img :   1  BIOS  y   none  0x0000  0x00      4         673\n"
        moved = report.replace("673", "999")
        self.assertEqual(iso.el_torito_entries(report), iso.el_torito_entries(moved))
        self.assertNotEqual(iso.el_torito_entries(report), iso.el_torito_entries(report.replace("BIOS", "UEFI")))

    def test_md5sums(self):
        text = f"{'a' * 32}  ./casper/minimal.squashfs\n{'b' * 32}  ./boot/grub/grub.cfg\n"
        out = iso.edit_md5sums(text, {"/casper/minimal.squashfs": "c" * 32, "/jeronix/x.deb": "d" * 32})
        self.assertIn(f"{'c' * 32}  ./casper/minimal.squashfs", out)
        self.assertIn(f"{'b' * 32}  ./boot/grub/grub.cfg", out)
        self.assertIn(f"{'d' * 32}  ./jeronix/x.deb", out)
        self.assertNotIn("a" * 32, out)


@unittest.skipUnless(have("mksquashfs", "unsquashfs"), "squashfs-tools not installed")
class LayerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        src = self.tmp / "src"
        (src / "usr/share/doc").mkdir(parents=True)
        (src / "usr/share/doc/keep").write_text("ubuntu file\n")
        (src / "etc").mkdir()
        (src / "usr/bin").mkdir()
        (src / "usr/bin/tool").write_text("#!/bin/sh\n")
        (src / "usr/bin/tool").chmod(0o4755)  # setuid must survive
        self.base = self.tmp / "base.squashfs"
        subprocess.run(["mksquashfs", src, self.base, "-noappend", "-quiet", "-no-progress", "-all-root",
                        "-comp", "gzip"], check=True)
        payload = self.tmp / "payload"
        (payload / "usr/share/jeronix").mkdir(parents=True)
        (payload / "usr/share/jeronix/hello").write_text("jeronix\n")
        (payload / "etc/dconf/profile").mkdir(parents=True)
        (payload / "etc/dconf/profile/user").write_text("user-db:user\n")
        for p in payload.rglob("*"):
            p.chmod(0o755 if p.is_dir() else 0o644)
        self.payload = payload

    def tearDown(self):
        self._tmp.cleanup()

    def test_rebuild_adds_payload_and_preserves_everything_else(self):
        work = self.tmp / "work"
        work.mkdir()
        new, defs = iso.rebuild_layer(self.base, self.payload, work, 1760000000)
        iso.compare_layers(self.base, new, defs)
        self.assertEqual(iso.squashfs_params(new)[0], "gzip", "compression follows the original")
        cat = subprocess.run(["unsquashfs", "-cat", new, "usr/share/jeronix/hello"], capture_output=True, text=True)
        self.assertEqual(cat.stdout, "jeronix\n")
        listing = subprocess.run(["unsquashfs", "-lls", new], capture_output=True, text=True).stdout
        self.assertIn("-rwsr-xr-x root/root", listing)
        self.assertRegex(listing, r"-rw-r--r-- root/root .* squashfs-root/usr/share/jeronix/hello")
        self.assertFalse((work / "base.pf").exists(), "the large pseudo file is removed")

    def test_payload_may_not_replace_ubuntu_files(self):
        (self.payload / "usr/share/doc").mkdir()
        (self.payload / "usr/share/doc/keep").write_text("replaced\n")
        with self.assertRaisesRegex(iso.BuildError, "replace files"):
            iso.payload_definitions(self.payload, iso.layer_paths(self.base), 0)

    def test_existing_directories_are_not_redefined(self):
        defs = iso.payload_definitions(self.payload, iso.layer_paths(self.base), 0)
        names = [d.split(" ")[0] for d in defs]
        self.assertNotIn("usr", names)
        self.assertNotIn("etc", names)
        self.assertIn("etc/dconf", names)
        self.assertIn("usr/share/jeronix/hello", names)

    def test_compare_detects_tampering(self):
        work = self.tmp / "work"
        work.mkdir()
        _, defs = iso.rebuild_layer(self.base, self.payload, work, 1760000000)
        tampered_src = self.tmp / "tampered"
        subprocess.run(["unsquashfs", "-q", "-d", tampered_src, self.base], check=True, capture_output=True)
        (tampered_src / "usr/share/doc/keep").write_text("changed by someone\n")
        tampered = self.tmp / "tampered.squashfs"
        subprocess.run(["mksquashfs", tampered_src, tampered, "-noappend", "-quiet", "-no-progress",
                        "-all-root"], check=True)
        with self.assertRaises(iso.BuildError):
            iso.compare_layers(self.base, tampered, defs)


class PreflightAndCliTests(unittest.TestCase):
    def test_missing_tools_name_packages(self):
        missing = iso.missing_tools(path="/nonexistent")
        self.assertEqual(missing["xorriso"], "xorriso")
        self.assertEqual(missing["mksquashfs"], "squashfs-tools")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(iso.BuildError, "sudo apt install .*xorriso"):
                iso.preflight(Path(tmp) / "w", Path(tmp) / "o", path="/nonexistent")

    def test_failed_build_leaves_no_partial_output(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            tmp = Path(tmp)
            env = dict(os.environ)
            result = subprocess.run(
                [str(ROOT / "scripts" / "build-iso.sh"), "--source-iso", str(tmp / "missing.iso"),
                 "--skip-tests", "--offline", "--out", str(tmp / "out"), "--work", str(tmp / "work"),
                 "--cache", str(tmp / "cache")], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("BUILD FAILED", result.stderr)
            self.assertEqual(sorted(p.suffix for p in (tmp / "out").iterdir()), [".log"])
            self.assertLessEqual({p.name for p in (tmp / "work").iterdir()}, {".lock"})


@unittest.skipUnless(have("xorriso"), "xorriso not installed")
class IsoReadTests(unittest.TestCase):
    def test_reads_rock_ridge_names_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "tree/casper").mkdir(parents=True)
            (tmp / "tree/casper/install-sources.yaml").write_text("version: 2\n")
            (tmp / "tree/.disk").mkdir()
            (tmp / "tree/.disk/info").write_text("Test image\n")
            subprocess.run(["xorriso", "-outdev", tmp / "t.iso", "-volid", "TESTVOL", "-map", tmp / "tree", "/"],
                           check=True, capture_output=True)
            with IsoImage(tmp / "t.iso") as image:
                self.assertEqual(image.volume_id, "TESTVOL")
                self.assertEqual(image.read("/casper/install-sources.yaml"), b"version: 2\n")
                self.assertEqual(image.read("/.disk/info"), b"Test image\n")
                self.assertFalse(image.exists("/nope"))


if __name__ == "__main__":
    unittest.main()
