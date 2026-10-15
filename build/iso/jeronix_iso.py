#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the JERONIX ISO by remastering the official Ubuntu Desktop ISO.

Approach (see build/iso/README.md and ADR 0003):

* The source ISO is downloaded only from the pinned official mirror and used
  only after its SHA-256 matches SHA256SUMS whose GPG signature verifies
  against the pinned Ubuntu CD image key in the system keyring.
* Boot files (shim, GRUB, kernel, initrd, EFI partition) are not modified:
  xorriso replays Ubuntu's BIOS/UEFI boot setup, so the Secure Boot chain
  is Canonical's own signed binaries.
* JERONIX is added to the base layer casper/minimal.squashfs, which every
  install source and the live session stack on top of. The layer is rebuilt
  without root: `unsquashfs -pf` describes every original file (owner, mode,
  xattrs, data) and mksquashfs rebuilds it plus the jeronix-desktop payload.
* Only text metadata on the ISO changes: GRUB menu titles, layer sizes in
  install-sources.yaml, md5sum.txt, plus a /jeronix directory with the .deb
  and the build manifest.

    scripts/build-iso.sh [--source-iso FILE] [--out DIR] [--work DIR]
                         [--keep-work] [--skip-tests] [--offline]
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packaging"))
from isoread import IsoImage  # noqa: E402

BASE = HERE / "base.json"
TRUSTED_MIRRORS = ("https://releases.ubuntu.com/", "https://cdimage.ubuntu.com/")
BASE_LAYER = "minimal.squashfs"
UPPER_LAYERS = ("minimal.standard.squashfs", "minimal.standard.live.squashfs")
# Boot-critical files that must be byte-identical to Ubuntu's (the signed
# UEFI chain, kernel and initrd).
BOOT_FILES = ("/casper/vmlinuz", "/casper/initrd", "/EFI/boot/bootx64.efi", "/EFI/boot/grubx64.efi",
              "/EFI/boot/mmx64.efi")
# The BIOS El Torito image is patched by xorriso on every mastering run
# (boot-info-table at bytes 8-63, grub2-boot-info at 2548-2555, both holding
# sector addresses); everything else in it must stay identical.
ELTORITO_IMG = "/boot/grub/i386-pc/eltorito.img"
ELTORITO_PATCHED = ((8, 64), (2548, 2556))
GRUB_TITLES = (("Try or Install Ubuntu", "Try or Install JERONIX"),
               ("Ubuntu (safe graphics)", "JERONIX (safe graphics)"))
SOURCE_NAMES = (("Ubuntu Desktop (minimized)", "JERONIX Desktop (minimized, Ubuntu base)"),
                ("Ubuntu Desktop", "JERONIX Desktop (Ubuntu base)"))
MIN_FREE_WORK = 25 * 2**30
MIN_FREE_OUT = 8 * 2**30

# tool -> Ubuntu package that provides it
TOOLS = {
    "xorriso": "xorriso", "mksquashfs": "squashfs-tools", "unsquashfs": "squashfs-tools",
    "gpgv": "gpgv", "wget": "wget", "sha256sum": "coreutils", "dpkg-deb": "dpkg",
    "dconf": "dconf-cli", "git": "git",
}

log = logging.getLogger("jeronix-iso")


class BuildError(Exception):
    pass


# -- helpers ----------------------------------------------------------------

def run(cmd, **kw):
    log.debug("$ %s", " ".join(map(str, cmd)))
    result = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if result.returncode != 0:
        raise BuildError(f"{Path(str(cmd[0])).name} failed ({result.returncode}):\n{result.stderr.strip()[-2000:]}")
    return result.stdout


def sha256(path, chunk=8 * 2**20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def md5_bytes(data):
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def md5_file(path, chunk=8 * 2**20):
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_base(path=BASE):
    base = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    if base.get("schema") != 1:
        problems.append("schema must be 1")
    if not base.get("mirror", "").startswith(TRUSTED_MIRRORS):
        problems.append(f"mirror must be one of {TRUSTED_MIRRORS}")
    if not re.fullmatch(r"[0-9A-F]{40}", base.get("signing_key", {}).get("fingerprint", "")):
        problems.append("signing_key.fingerprint must be 40 upper-case hex digits")
    u = base.get("ubuntu", {})
    if base.get("iso") != f"ubuntu-{u.get('version')}-{u.get('flavor')}-{u.get('arch')}.iso":
        problems.append("iso name does not match ubuntu version/flavor/arch")
    if u.get("arch") != "amd64":
        problems.append("only amd64 is supported")
    if problems:
        raise BuildError("build/iso/base.json is invalid: " + "; ".join(problems))
    return base


# -- source verification ------------------------------------------------------

def check_signature_status(status_output, fingerprint):
    """Accepts gpgv --status-fd output only with a VALIDSIG by the pinned key."""
    lines = status_output.splitlines()
    if any(l.startswith(("[GNUPG:] BADSIG", "[GNUPG:] ERRSIG", "[GNUPG:] EXPKEYSIG",
                         "[GNUPG:] REVKEYSIG")) for l in lines):
        raise BuildError("SHA256SUMS signature is bad, expired or revoked")
    valid = [l.split()[2] for l in lines if l.startswith("[GNUPG:] VALIDSIG ") and len(l.split()) > 2]
    if fingerprint not in valid:
        raise BuildError(f"SHA256SUMS is not signed by the pinned key {fingerprint} (found: {valid or 'none'})")


def verify_signature(sums, sig, key):
    keyring = Path(key["keyring"])
    if not keyring.is_file():
        raise BuildError(f"keyring {keyring} missing (package ubuntu-keyring)")
    result = subprocess.run(["gpgv", "--keyring", str(keyring), "--status-fd", "1", str(sig), str(sums)],
                            capture_output=True, text=True)
    check_signature_status(result.stdout, key["fingerprint"])
    log.info("SHA256SUMS signature verified: %s", key["fingerprint"])


def expected_checksum(sums_text, iso_name):
    found = []
    for line in sums_text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line.strip())
        if m and m.group(2) == iso_name:
            found.append(m.group(1))
    if len(found) != 1:
        raise BuildError(f"SHA256SUMS has {len(found)} entries for {iso_name}, expected exactly 1")
    return found[0]


def verify_iso(iso, sums_text, iso_name):
    want = expected_checksum(sums_text, iso_name)
    log.info("hashing %s ...", iso)
    got = sha256(iso)
    if got != want:
        raise BuildError(f"{iso} SHA-256 mismatch: expected {want}, got {got}")
    log.info("source ISO verified: sha256 %s", got)
    return got


def download(url, dest):
    log.info("downloading %s", url)
    run(["wget", "-c", "-q", "--https-only", "-O", dest, url])


def obtain_source(base, cache, source_iso=None, offline=False):
    cache.mkdir(parents=True, exist_ok=True)
    sums, sig = cache / base["checksums"], cache / base["signature"]
    if not offline:
        for name, path in ((base["checksums"], sums), (base["signature"], sig)):
            path.unlink(missing_ok=True)
            download(base["mirror"] + name, path)
    elif not (sums.is_file() and sig.is_file()):
        raise BuildError(f"--offline needs cached {sums.name} and {sig.name} in {cache}")
    verify_signature(sums, sig, base["signing_key"])
    sums_text = sums.read_text(encoding="utf-8")
    if source_iso:
        iso = Path(source_iso).resolve()
        if not iso.is_file():
            raise BuildError(f"source ISO {iso} does not exist")
    else:
        iso = cache / base["iso"]
        if not iso.is_file():
            if offline:
                raise BuildError(f"--offline but {iso} is not cached")
            part = iso.with_suffix(".iso.part")
            download(base["mirror"] + base["iso"], part)
            part.rename(iso)
    try:
        digest = verify_iso(iso, sums_text, base["iso"])
    except BuildError:
        if not source_iso:
            iso.rename(iso.with_suffix(".iso.bad"))  # never reuse a corrupt download
        raise
    return iso, digest


# -- preflight ----------------------------------------------------------------

def missing_tools(path=None):
    return {t: pkg for t, pkg in TOOLS.items() if not shutil.which(t, path=path)}


def fs_type(path):
    return subprocess.run(["stat", "-f", "-c", "%T", str(path)], capture_output=True, text=True).stdout.strip()


def preflight(work, out, path=None):
    problems = []
    missing = missing_tools(path)
    if missing:
        pkgs = " ".join(sorted(set(missing.values())))
        problems.append(f"missing tools: {', '.join(sorted(missing))}. Install with: sudo apt install {pkgs}")
    try:
        import gi  # noqa: F401
        from gi.repository import Gio  # noqa: F401
    except ImportError:
        problems.append("python3-gi is required (validates the Pure layout against GSettings schemas)")
    for d, need in ((work, MIN_FREE_WORK), (out, MIN_FREE_OUT)):
        d.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(d).free
        if free < need:
            problems.append(f"{d}: {free / 2**30:.1f} GiB free, need {need / 2**30:.0f} GiB")
        if fs_type(d) == "tmpfs":
            problems.append(f"{d} is on tmpfs (RAM); use a disk directory")
    if os.geteuid() == 0:
        problems.append("do not run the builder as root; it needs no privileges")
    if problems:
        raise BuildError("preflight failed:\n  " + "\n  ".join(problems))
    log.info("preflight ok")


# -- ISO metadata edits ---------------------------------------------------------

def edit_grub_cfg(text):
    for old, new in GRUB_TITLES:
        if old not in text:
            raise BuildError(f"grub.cfg: expected menu entry {old!r} not found")
        text = text.replace(f'"{old}"', f'"{new}"')
    return text


def edit_install_sources(text, added_bytes):
    """Adds the payload size to every layer size and renames the sources."""
    def bump(m):
        return f"{m.group(1)}size: {int(m.group(2)) + added_bytes}"
    text, count = re.subn(r"(?m)^(\s*)size: (\d+)$", bump, text)
    if count == 0:
        raise BuildError("install-sources.yaml: no size fields found")
    for old, new in SOURCE_NAMES:
        text, n = re.subn(rf"(?m)^(\s+en: ){re.escape(old)}$", rf"\g<1>{new}", text)
        if n != 1:
            raise BuildError(f"install-sources.yaml: source name {old!r} found {n} times")
    return text


def edit_md5sums(text, changed):
    """changed: {iso_path: md5}. Replaces or adds './path' lines."""
    lines, seen = [], set()
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{32})  \./(.+)", line)
        if m and "/" + m.group(2) in changed:
            path = "/" + m.group(2)
            lines.append(f"{changed[path]}  ./{m.group(2)}")
            seen.add(path)
        else:
            lines.append(line)
    for path in sorted(set(changed) - seen):
        lines.append(f"{changed[path]}  .{path}")
    return "\n".join(lines) + "\n"


# -- base layer -------------------------------------------------------------------

def layer_paths(squashfs):
    """Every path in a squashfs image (files and directories), relative."""
    out = run(["unsquashfs", "-l", "-d", "", squashfs])
    return {l.strip().lstrip("/") for l in out.splitlines() if l.strip()}


def payload_definitions(root, existing, mtime):
    """Pseudo definitions adding the payload tree; refuses to replace any
    existing file and only creates directories that do not exist yet."""
    defs, collisions = [], []
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if " " in rel or "\n" in rel:
            raise BuildError(f"payload path with whitespace: {rel}")
        mode = f"{p.stat().st_mode & 0o7777:o}"
        if p.is_dir():
            if rel not in existing:
                defs.append(f"{rel} D {mtime} {mode} 0 0")
        elif rel in existing:
            collisions.append(rel)
        else:
            defs.append(f"{rel} F {mtime} {mode} 0 0 cat {p}")
    if collisions:
        raise BuildError(f"payload would replace files of the Ubuntu base layer: {collisions[:10]}")
    return defs


def squashfs_params(squashfs):
    info = run(["unsquashfs", "-s", squashfs])
    comp = re.search(r"^Compression (\w+)", info, re.M)
    block = re.search(r"^Block size (\d+)", info, re.M)
    if not comp or not block:
        raise BuildError(f"cannot read squashfs parameters of {squashfs}")
    return comp.group(1), int(block.group(1))


def rebuild_layer(original, payload_root, work, mtime):
    comp, block = squashfs_params(original)
    existing = layer_paths(original)
    defs = payload_definitions(payload_root, existing, mtime)
    add_pf = work / "jeronix.pf"
    add_pf.write_text("\n".join(defs) + "\n", encoding="utf-8")
    base_pf = work / "base.pf"
    log.info("describing %s (unsquashfs -pf) ...", original.name)
    run(["unsquashfs", "-pf", base_pf, original])
    new = work / "minimal.squashfs.new"
    new.unlink(missing_ok=True)
    log.info("rebuilding %s with %d JERONIX entries (%s, %d-byte blocks); this takes a while ...",
             original.name, len(defs), comp, block)
    run(["mksquashfs", "-", new, "-pf", base_pf, "-pf", add_pf, "-comp", comp, "-b", block,
         "-noappend", "-no-progress", "-quiet", "-exit-on-error", "-mkfs-time", mtime])
    base_pf.unlink()
    return new, defs


def compare_layers(original, rebuilt, payload_defs):
    """Every original entry must be unchanged; extra entries must be the payload."""
    def listing(img):
        out = run(["unsquashfs", "-lls", "-d", "", img])
        entries = {}
        for line in out.splitlines():
            parts = line.split(None, 5)
            if len(parts) >= 5:
                entries[parts[5] if len(parts) == 6 else "/"] = line.rstrip()
        return entries
    before, after = listing(original), listing(rebuilt)
    expected = {d.split(" ", 1)[0] for d in payload_defs}

    def same(path, old, new):
        # A squashfs directory's size field reflects how its index headers
        # pack inode numbers, which shift whenever entries are added, so it
        # is not content. Directory children are compared via the path set.
        if new is None:
            return False
        if old == new:
            return True
        o, n = old.split(None, 5), new.split(None, 5)
        return o[0].startswith("d") and o[:2] + o[3:] == n[:2] + n[3:]
    changed = [p for p, l in before.items() if not same(p, l, after.get(p))]
    if changed:
        raise BuildError(f"rebuilt layer changed {len(changed)} original entries, e.g. {changed[:5]}")
    added = {p.lstrip("/") for p in set(after) - set(before)}
    if added != expected:
        raise BuildError(f"rebuilt layer added unexpected entries: {sorted(added ^ expected)[:10]}")

    def xattrs(img):
        proc = subprocess.Popen(["unsquashfs", "-pf", "-", str(img)], stdout=subprocess.PIPE)
        found = set()
        for raw in proc.stdout:
            if raw.startswith(b"# START OF DATA"):
                break
            if b" x " in raw:
                found.add(raw)
        proc.stdout.close()
        proc.kill()
        proc.wait()
        return found
    if xattrs(original) != xattrs(rebuilt):
        raise BuildError("rebuilt layer lost or changed extended attributes (file capabilities)")
    log.info("rebuilt layer: %d original entries identical, xattrs identical, %d added",
             len(before), len(added))


# -- assembly and validation --------------------------------------------------------

def assemble(source, out_iso, maps, removals=()):
    cmd = ["xorriso", "-abort_on", "FAILURE", "-return_with", "SORRY", "0",
           "-indev", source, "-outdev", out_iso, "-boot_image", "any", "replay"]
    for path in removals:
        cmd += ["-rm_r", path]
    for disk, iso_path in maps:
        cmd += ["-map", disk, iso_path]
    cmd += ["-commit"]
    log.info("assembling %s with xorriso (boot setup replayed from the Ubuntu ISO) ...", out_iso.name)
    run(cmd)


def boot_report(iso):
    el_torito = run(["xorriso", "-indev", iso, "-report_el_torito", "plain"], )
    system_area = run(["xorriso", "-indev", iso, "-report_system_area", "plain"])
    return el_torito, system_area


def boot_summary(report):
    el_torito, system_area = report
    platforms = re.findall(r"El Torito boot img :\s+\d+\s+(\S+)", el_torito)
    return {
        "bios_el_torito": "BIOS" in platforms,
        "uefi_el_torito": "UEFI" in platforms,
        "gpt": "GPT" in system_area,
        "mbr": "MBR" in system_area,
        "efi_partition": efi_partition(system_area) is not None,
    }


# EFI System Partition type GUID c12a7328-f81f-11d2-ba4b-00a0c93ec93b as
# xorriso prints it (mixed-endian bytes).
ESP_GUID = "28732ac11ff8d211ba4b00a0c93ec93b"


def efi_partition(system_area):
    """(start, size) in 512-byte sectors of the GPT EFI System Partition."""
    number = re.search(rf"(?m)^GPT type GUID\s*:\s*(\d+)\s+{ESP_GUID}$", system_area)
    if not number:
        return None
    span = re.search(rf"(?m)^GPT start and size :\s*{number.group(1)}\s+(\d+)\s+(\d+)$", system_area)
    return (int(span.group(1)), int(span.group(2))) if span else None


def unpatched_differences(a, b, patched=ELTORITO_PATCHED):
    """Byte offsets where a and b differ outside the patched ranges."""
    if len(a) != len(b):
        return ["length"]
    return [i for i, (x, y) in enumerate(zip(a, b))
            if x != y and not any(lo <= i < hi for lo, hi in patched)]


def el_torito_entries(report):
    """El Torito boot entries without their sector address (last column)."""
    return [line.split()[:-1] for line in report.splitlines() if line.startswith("El Torito boot img")]


def efi_partition_digest(image, system_area):
    start, size = efi_partition(system_area)
    h = hashlib.sha256()
    with open(image, "rb") as f:
        f.seek(start * 512)
        h.update(f.read(size * 512))
    return h.hexdigest()


def validate(source, out_iso, payload_root, expected_changes, sums_ok_paths):
    """Checks the output image independently of xorriso where possible."""
    problems = []
    src_size, out_size = source.stat().st_size, out_iso.stat().st_size
    if not 0.9 * src_size < out_size < 1.5 * src_size:
        problems.append(f"implausible size {out_size} (source {src_size})")
    src_report, out_report = boot_report(source), boot_report(out_iso)
    src_boot, out_boot = boot_summary(src_report), boot_summary(out_report)
    if out_boot != src_boot:
        problems.append(f"boot setup differs from Ubuntu's: {src_boot} -> {out_boot}")
    if el_torito_entries(src_report[0]) != el_torito_entries(out_report[0]):
        problems.append("El Torito boot entries differ from Ubuntu's (beyond sector addresses)")
    if not all(out_boot.values()):
        problems.append(f"missing BIOS/UEFI boot entry, GPT, MBR or EFI partition: {out_boot}")
    else:
        # The EFI partition holds Canonical's signed shim and GRUB.
        src_esp = efi_partition_digest(source, src_report[1])
        out_esp = efi_partition_digest(out_iso, out_report[1])
        if src_esp != out_esp:
            problems.append("EFI system partition differs from Ubuntu's")
        out_boot["efi_partition_sha256"] = out_esp
        out_boot["efi_partition_identical_to_ubuntu"] = src_esp == out_esp
    with IsoImage(source) as src, IsoImage(out_iso) as out:
        if out.volume_id != src.volume_id:
            problems.append(f"volume id changed: {src.volume_id} -> {out.volume_id}")
        for path in BOOT_FILES:
            if src.exists(path) and md5_bytes(src.read(path)) != md5_bytes(out.read(path)):
                problems.append(f"boot file changed: {path}")
            if not out.exists(path):
                problems.append(f"missing boot file: {path}")
        diffs = unpatched_differences(src.read(ELTORITO_IMG), out.read(ELTORITO_IMG))
        if diffs:
            problems.append(f"{ELTORITO_IMG} differs outside xorriso's boot-info fields at {diffs[:8]}")
        grub = out.read("/boot/grub/grub.cfg").decode()
        if "Try or Install JERONIX" not in grub:
            problems.append("grub.cfg has no JERONIX entry")
        for path in ("/jeronix/BUILD-MANIFEST.json", "/casper/install-sources.yaml", "/.disk/info"):
            if not out.exists(path):
                problems.append(f"missing {path}")
        md5 = out.read("/md5sum.txt").decode()
        listed = dict((p, h) for h, p in re.findall(r"(?m)^([0-9a-f]{32})  \.(/\S+)$", md5))
        for path in sums_ok_paths:
            if path not in listed:
                problems.append(f"md5sum.txt lacks {path}")
            elif path != f"/casper/{BASE_LAYER}" and md5_bytes(out.read(path)) != listed[path]:
                problems.append(f"md5sum.txt wrong for {path}")
        layer = out.lookup(f"/casper/{BASE_LAYER}")
        layer_md5 = hashlib.md5(usedforsecurity=False)
        out.f.seek(layer["extent"] * 2048)
        remaining = layer["size"]
        while remaining:
            block = out.f.read(min(remaining, 8 * 2**20))
            layer_md5.update(block)
            remaining -= len(block)
        if listed.get(f"/casper/{BASE_LAYER}") != layer_md5.hexdigest():
            problems.append("md5sum.txt wrong for the rebuilt base layer")
    if problems:
        raise BuildError("output validation failed:\n  " + "\n  ".join(problems))
    log.info("output validated: boot setup %s, boot files identical, metadata consistent", out_boot)
    return out_boot


def jeronix_revision():
    head = run(["git", "-C", ROOT, "rev-parse", "--short=12", "HEAD"]).strip()
    dirty = bool(run(["git", "-C", ROOT, "status", "--porcelain"]).strip())
    return {"commit": head, "dirty": dirty}


LIMITATIONS = [
    "The Ubuntu installer (ubuntu-desktop-bootstrap), Plymouth boot splash and GDM login screen keep Ubuntu "
    "branding; changing them needs packages built for the initrd and GDM (planned, Milestone 7).",
    "/etc/os-release still identifies the system as Ubuntu; JERONIX identifies itself in /etc/jeronix-release.",
    "JERONIX files in the image are not registered with dpkg. Installing the shipped .deb "
    "(/cdrom/jeronix/*.deb) on the installed system registers them.",
    "Layout Studio, the JERONIX dock, and the Welcome, Settings and System Information apps are not "
    "implemented and are not included.",
    "The shell theme and Pure defaults are tested headlessly; a full live-session and installation test "
    "has not been recorded for this build.",
]


# -- main build ------------------------------------------------------------------

def build(args):
    base = load_base()
    out_dir, work = args.out.resolve(), args.work.resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc)
    preflight(work, out_dir)
    lock = open(work / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BuildError(f"another build is running in {work}")

    if not args.skip_tests:
        log.info("running the JERONIX test suite ...")
        result = subprocess.run([str(ROOT / "scripts" / "run-tests.sh"), "all"], capture_output=True, text=True)
        tests_log = out_dir / f"tests-{stamp.strftime('%Y%m%dT%H%M%SZ')}.log"
        tests_log.write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise BuildError(f"test suite failed; see {tests_log}")
        log.info("test suite passed")

    iso, src_sha = obtain_source(base, args.cache.resolve(), args.source_iso, args.offline)
    stage = work / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    with IsoImage(iso) as src:
        for required in (f"/casper/{BASE_LAYER}", "/casper/install-sources.yaml", "/boot/grub/grub.cfg",
                         "/md5sum.txt", "/.disk/info") + tuple(f"/casper/{l}" for l in UPPER_LAYERS):
            if not src.exists(required):
                raise BuildError(f"source ISO lacks {required}; unexpected Ubuntu image layout")
        sources = src.read("/casper/install-sources.yaml").decode()
        if f"path: {BASE_LAYER}" not in sources:
            raise BuildError("install-sources.yaml does not use minimal.squashfs as the base layer")
        texts = {p: src.read(p).decode() for p in ("/boot/grub/grub.cfg", "/boot/grub/loopback.cfg",
                                                   "/md5sum.txt", "/.disk/info", f"/casper/{BASE_LAYER[:-9]}.size")
                 if src.exists(p)}
        log.info("extracting layers from %s ...", iso.name)
        layers = {}
        for name in (BASE_LAYER,) + UPPER_LAYERS:
            node = src.lookup(f"/casper/{name}")
            dest = stage / name
            with open(dest, "wb") as f:
                src.f.seek(node["extent"] * 2048)
                remaining = node["size"]
                while remaining:
                    block = src.f.read(min(remaining, 8 * 2**20))
                    f.write(block)
                    remaining -= len(block)
            layers[name] = dest
    ubuntu_info = texts["/.disk/info"].strip()

    # The base image's own dconf user profile, if it ships one, is extended
    # rather than replaced; upper layers must not shadow JERONIX paths.
    if "etc/dconf/profile/user" in layer_paths(layers[BASE_LAYER]):
        # Replacing it would drop Ubuntu's settings; not needed for 26.04.1.
        raise BuildError("base layer ships /etc/dconf/profile/user; merging it is not implemented")

    import jeronix_payload
    payload_out = work / "payload"
    if payload_out.exists():
        shutil.rmtree(payload_out)
    payload_out.mkdir()
    deb = jeronix_payload.build_deb(payload_out)
    payload_root = payload_out / "root"
    payload_files = sorted(str(p.relative_to(payload_root)) for p in payload_root.rglob("*") if p.is_file())
    for upper in UPPER_LAYERS:
        shadowed = set(payload_files) & layer_paths(layers[upper])
        if shadowed:
            raise BuildError(f"{upper} would hide JERONIX files: {sorted(shadowed)[:5]}")
        layers[upper].unlink()
    payload_bytes = sum((payload_root / f).stat().st_size for f in payload_files)

    mtime = int(run(["git", "-C", ROOT, "log", "-1", "--format=%ct"]).strip())
    new_layer, defs = rebuild_layer(layers[BASE_LAYER], payload_root, work, mtime)
    compare_layers(layers[BASE_LAYER], new_layer, defs)
    layers[BASE_LAYER].unlink()

    # Text metadata on the ISO.
    files = {}

    def put_text(iso_path, text):
        dest = stage / iso_path.lstrip("/").replace("/", "__")
        dest.write_text(text, encoding="utf-8")
        files[iso_path] = dest

    put_text("/boot/grub/grub.cfg", edit_grub_cfg(texts["/boot/grub/grub.cfg"]))
    if "/boot/grub/loopback.cfg" in texts:
        lb = texts["/boot/grub/loopback.cfg"]
        for old, new in GRUB_TITLES:
            lb = lb.replace(f'"{old}"', f'"{new}"')
        put_text("/boot/grub/loopback.cfg", lb)
    put_text("/casper/install-sources.yaml", edit_install_sources(sources, payload_bytes))
    size_path = f"/casper/{BASE_LAYER[:-9]}.size"
    if size_path in texts:
        put_text(size_path, f"{int(texts[size_path].strip()) + payload_bytes}\n")

    revision = jeronix_revision()
    config = jeronix_payload.load_config()
    manifest = {
        "name": "JERONIX",
        "jeronix_version": config["version"],
        "jeronix_revision": revision,
        "built": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base": {"ubuntu": base["ubuntu"], "iso": base["iso"], "iso_sha256": src_sha, "disk_info": ubuntu_info,
                 "signing_key": base["signing_key"]["fingerprint"]},
        "architecture": "x86_64 (amd64)",
        "components": {
            "jeronix-desktop": {"version": config["version"], "deb": deb.name,
                                "extensions": config["enabled_extensions"], "layout": "pure",
                                "files": payload_files},
        },
        "changed_on_iso": [f"/casper/{BASE_LAYER}", *sorted(files), "/md5sum.txt", "/jeronix/*",
                           "/.disk/jeronix-info"],
        "unchanged_boot_files": list(BOOT_FILES),
        "tools": {t: run([t, "-version"] if t in ("xorriso", "mksquashfs") else [t, "--version"]).splitlines()[0]
                  for t in ("xorriso", "mksquashfs")},
        "limitations": LIMITATIONS,
    }
    put_text("/jeronix/BUILD-MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    put_text("/jeronix/README.txt", (
        f"JERONIX {config['version']} for x86_64, based on {ubuntu_info}.\n\n"
        "jeronix-desktop_*.deb contains the same JERONIX files that are preinstalled by this image.\n"
        "Install it after installation to register them with dpkg:\n"
        "  sudo apt install /cdrom/jeronix/" + deb.name + "\n\n"
        "BUILD-MANIFEST.json lists the base image, revision, components and known limitations.\n"))
    put_text("/.disk/jeronix-info", f"JERONIX {config['version']} ({revision['commit']}"
             f"{'+dirty' if revision['dirty'] else ''}) based on {ubuntu_info}\n")
    files["/jeronix/" + deb.name] = deb
    files[f"/casper/{BASE_LAYER}"] = new_layer

    changed_md5 = {p: (md5_file(d)) for p, d in files.items()}
    put_text("/md5sum.txt", edit_md5sums(texts["/md5sum.txt"], changed_md5))

    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / base["output"]["name"]
    partial = final.with_suffix(".iso.part")
    partial.unlink(missing_ok=True)
    try:
        assemble(iso, partial, [(d, p) for p, d in sorted(files.items())])
        boot = validate(iso, partial, payload_root, changed_md5, [p for p in changed_md5 if p != "/md5sum.txt"])
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(final)
    digest = sha256(final)
    sha_file = final.with_name(final.name + ".sha256")
    sha_file.write_text(f"{digest}  {final.name}\n", encoding="utf-8")
    run(["sha256sum", "-c", sha_file.name], cwd=out_dir)
    manifest["output"] = {"file": final.name, "size": final.stat().st_size, "sha256": digest, "boot": boot}
    (out_dir / (final.stem + ".manifest.json")).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(deb, out_dir / deb.name)
    log.info("DONE %s (%d bytes) sha256 %s", final, final.stat().st_size, digest)
    return final


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the JERONIX ISO from the official Ubuntu Desktop ISO.")
    ap.add_argument("--source-iso", type=Path, help="use this local Ubuntu ISO (still checksum-verified)")
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "iso")
    ap.add_argument("--work", type=Path, default=Path.home() / ".cache" / "jeronix" / "iso-work")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "jeronix" / "iso")
    ap.add_argument("--keep-work", action="store_true", help="keep the work directory after the build")
    ap.add_argument("--skip-tests", action="store_true", help="do not run scripts/run-tests.sh first")
    ap.add_argument("--offline", action="store_true", help="use cached SHA256SUMS and ISO, no network")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    logfile = args.out / f"build-{time.strftime('%Y%m%dT%H%M%S')}.log"
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(logfile)])
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("==> %(message)s"))
    logging.getLogger().addHandler(console)
    log.info("log: %s", logfile)
    ok = False
    try:
        build(args)
        ok = True
        return 0
    except BuildError as e:
        log.error("BUILD FAILED: %s", e)
        return 1
    except KeyboardInterrupt:
        log.error("BUILD INTERRUPTED")
        return 130
    finally:
        work = args.work.resolve()
        if work.exists() and not args.keep_work:
            for child in work.iterdir():
                if child.name != ".lock":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            log.info("work directory cleaned%s", "" if ok else " (use --keep-work to inspect failures)")


if __name__ == "__main__":
    sys.exit(main())
