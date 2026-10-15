# ADR 0003: Build the ISO by remastering Ubuntu's base layer

Status: accepted (2026-10-15)

## Context

JERONIX needs a bootable, installable x86_64 image based on Ubuntu 26.04.1
Desktop. Inspecting the official ISO showed:

- It uses layered squashfs images, chained by name: `minimal` →
  `minimal.standard` → `minimal.standard.live`, with language and
  `enhanced-secureboot` variants (about 70 files). `install-sources.yaml`
  defines two install sources, `minimal.squashfs` (the default) and
  `minimal.standard.squashfs`. Both include `minimal`, and so does the live
  session.
- No layer ships `/etc/dconf/profile/user`, and no layer contains any path
  JERONIX installs.
- Boot uses Canonical-signed shim and GRUB for both BIOS and UEFI.
- The build VM has no root without a password and no KVM.

## Decision

1. Remaster the official ISO; don't build from debootstrap. The Ubuntu
   installer, signed boot chain, kernel and initrd stay exactly as released.
2. Add JERONIX to `casper/minimal.squashfs`, which every install and the
   live session contain. Inserting a new layer would mean renaming the whole
   layer chain and editing the kernel command line.
3. Rebuild that layer without root through squashfs-tools pseudo files
   (`unsquashfs -pf`, then `mksquashfs -pf`). Verify the result entry by
   entry against the original, including xattrs.
4. Ship JERONIX defaults as a dconf **system database** (`system-db:jeronix`).
   Users can change and reset every key; nothing is locked. The theme and
   Stay Awake extensions are enabled by default through the same database.
5. Trust only `SHA256SUMS` signed by the pinned Ubuntu CD image key, checked
   against the package-managed `ubuntu-keyring`.
6. Assemble with `xorriso -boot_image any replay` and keep the volume ID
   unchanged.

## Consequences

- The Secure Boot chain is Ubuntu's own: the builder verifies that boot
  files are byte-identical. That keeps Secure Boot *compatible*, but it is
  not proof that it works. It must be booted with Secure Boot on to claim
  that.
- JERONIX files in the image aren't registered with dpkg (the dpkg status
  file lives in several layers). The `.deb` on the ISO registers them when
  installed. Packaging (M7) will add a proper APT repository.
- The installer, Plymouth, GDM and `os-release` still say Ubuntu. Changing
  them needs initrd/GDM packaging work and is deferred.
- Rebuilding a 3.3 GiB xz layer takes several minutes, and the build needs
  about 25 GiB of scratch space.
