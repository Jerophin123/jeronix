# JERONIX ISO builder

Builds `out/iso/jeronix-26.04-x86_64.iso` by remastering the official
Ubuntu 26.04.1 Desktop ISO (amd64). No root is needed. The decision record
is [ADR 0003](../../docs/architecture/decisions/0003-iso-remastering.md).

```sh
scripts/build-iso.sh                         # download, verify, build, validate
scripts/build-iso.sh --source-iso FILE.iso   # use a local copy (still verified)
scripts/build-iso.sh --offline               # cached ISO and SHA256SUMS only
scripts/build-iso.sh --keep-work             # keep the work directory for debugging
```

## Requirements

| Need | Package | Why |
| --- | --- | --- |
| `xorriso` | `xorriso` | Assembles the ISO and replays Ubuntu's BIOS/UEFI boot setup |
| `mksquashfs`, `unsquashfs` ≥ 4.6 | `squashfs-tools` | Rebuild the base layer without root (pseudo files) |
| `gpgv` and `/usr/share/keyrings/ubuntu-archive-keyring.gpg` | `gpgv`, `ubuntu-keyring` | Verify Ubuntu's signed `SHA256SUMS` |
| `wget`, `dpkg-deb`, `dconf`, `git`, `python3-gi` | standard on Ubuntu Desktop | Download, package, compile dconf defaults, record revision |
| ~25 GiB free on a disk (not tmpfs) for `--work`, ~8 GiB for `--out` | | |

Build on Ubuntu 26.04 Desktop. The Pure layout is validated against this
machine's GSettings schemas, which must match the target release.

Missing tools are reported with the exact `sudo apt install` line. The
builder never calls sudo itself.

## Pipeline

1. **Preflight**: tools, disk space, no tmpfs work directory, not running
   as root, one build at a time (lock file).
2. **Tests**: `scripts/run-tests.sh all` must pass (`--skip-tests` to skip).
3. **Source**: `SHA256SUMS` and `SHA256SUMS.gpg` are fetched from
   `releases.ubuntu.com` over HTTPS. `gpgv` must report `VALIDSIG` for the
   pinned fingerprint in [base.json](base.json), using the key from the
   system's package-managed `ubuntu-keyring`, not from the download. The ISO
   is used only if its SHA-256 matches. A mismatching download is renamed
   `*.iso.bad` and never reused.
4. **Inspect**: the expected layout (`casper/minimal.squashfs` as the base
   layer, `install-sources.yaml`, `grub.cfg`) is confirmed with
   [isoread.py](isoread.py). The builder also checks that no upper layer
   would hide JERONIX files.
5. **Payload**: [packaging/jeronix_payload.py](../../packaging/jeronix_payload.py)
   builds `jeronix-desktop_*.deb` and its file tree from the repository.
6. **Base layer**: `unsquashfs -pf` describes every original file (owner,
   mode, xattrs such as file capabilities). `mksquashfs` rebuilds the layer
   from that plus the payload, using the same compression and block size. It
   then checks that every original entry and every xattr is unchanged and
   that only the payload was added.
7. **Metadata**: GRUB menu titles, source names and sizes in
   `install-sources.yaml`, `minimal.size`, and `md5sum.txt` are updated.
   `/jeronix/` gets the `.deb`, a README and `BUILD-MANIFEST.json`, and
   `/.disk/jeronix-info` is added.
8. **Assemble**: `xorriso -boot_image any replay` writes the new image with
   Ubuntu's El Torito (BIOS and UEFI) entries, hybrid MBR/GPT and EFI
   partition.
9. **Validate**: size plausibility, an identical boot setup report,
   byte-identical signed UEFI files, kernel and initrd, an identical EFI
   partition, the BIOS GRUB image identical outside its boot-info fields,
   matching El Torito entries, volume ID, a JERONIX
   GRUB entry, and `md5sum.txt` correct for every changed file. Then the
   SHA-256 file is written and checked.
10. **Cleanup**: the work directory is emptied (failed builds too, unless
    `--keep-work`), and a partial `*.iso.part` is deleted on failure.

## Outputs (`out/iso/`, Git-ignored)

| File | Content |
| --- | --- |
| `jeronix-26.04-x86_64.iso` | The bootable image |
| `jeronix-26.04-x86_64.iso.sha256` | `sha256sum -c` compatible |
| `jeronix-26.04-x86_64.manifest.json` | Base ISO and its SHA-256, JERONIX revision (and whether the tree was dirty), build time, components, files, tool versions, boot report, limitations |
| `jeronix-desktop_<version>_all.deb` | The JERONIX layer as a package |
| `build-*.log`, `tests-*.log` | Full debug log and test-suite output |

## What changes in the image

| Changed | Unchanged |
| --- | --- |
| `casper/minimal.squashfs` (JERONIX files added) | shim, GRUB EFI, MOK manager, EFI partition (byte-identical); GRUB BIOS image except the boot-info fields xorriso patches on every mastering |
| `boot/grub/grub.cfg`, `loopback.cfg` (menu titles only) | kernel, initrd, kernel command lines |
| `casper/install-sources.yaml` (names and sizes), `minimal.size` | all other squashfs layers, language packs |
| `md5sum.txt`, `.disk/info` (product line: "JERONIX 26.04 ...", which the installer shows) | volume ID, APT pool |
| added: `/jeronix/`, `/.disk/jeronix-info` | the Ubuntu installer snap (signed); JERONIX brands it through its own interface, `/usr/share/desktop-provision/` in the payload ([jeronix_installer.py](../../packaging/jeronix_installer.py)) |
