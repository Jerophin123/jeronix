# Milestone 1: environment audit

Audited 2026-10-15 on the development VM (`jero@vmware`). Every value below
was read from the machine, not assumed.

## Platform

| Item | Value | Source |
| --- | --- | --- |
| OS | Ubuntu 26.04.1 LTS (resolute) | `/etc/os-release` |
| Kernel | 7.0.0-38-generic, x86_64 | `uname -a` |
| Virtualization | VMware guest | `systemd-detect-virt` |
| CPU | 4 vCPUs, **no VT-x/AMD-V exposed** (0 `vmx`/`svm` flags) | `/proc/cpuinfo` |
| Memory | 7.8 GiB RAM, 4 GiB swap | `free -h` |
| Disk | 95 GB root, 80 GB free | `df -h` |
| Session | GNOME on Wayland (seat0, tty2) | `loginctl` |
| sudo | Interactive password required | `sudo -n true` |

## GNOME stack

| Component | Version |
| --- | --- |
| GNOME Shell / Mutter | 50.1 |
| GJS | 1.88.0 |
| GTK 4 | 4.22.4 |
| libadwaita | 1.9.1 |
| GLib | 2.88.0 |
| Python / PyGObject | 3.14.3 / 3.56.2 |

These versions are recorded centrally in [config/platform.json](../../config/platform.json),
and tests check extension manifests against that file.

Enabled system extensions: `ding`, `ubuntu-dock`, `tiling-assistant`,
`ubuntu-appindicators`, `snapd-prompting`, `snapd-search-provider` and
`web-search-provider`. JERONIX's dock and layout extensions will have to
coexist with, or deliberately replace, `ubuntu-dock` and `ding` (see Risks).

## APT sources

The VM uses the official archive (`in.archive.ubuntu.com`) for resolute,
resolute-updates and resolute-backports, plus `security.ubuntu.com` for
resolute-security. Security updates are enabled; leave them that way.

## Packages

Installed and in use: git, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1,
libglib2.0-bin, appstream, desktop-file-utils and squashfs-tools.

Not installed. Install each group when its milestone starts (this needs sudo):

| Milestone | Packages |
| --- | --- |
| M3/M4 visual testing (optional) | `mutter-dev-bin` (provides `gnome-shell --devkit`) |
| M5–M6 tooling (optional) | `python3-pytest`, `shellcheck` |
| M7 packaging | `debhelper`, `dpkg-dev`, `devscripts`, `lintian` |
| M8 image | `xorriso`, `mtools`, `debootstrap`, `qemu-system-x86`, `ovmf` |

## Repository

`~/Projects/jeronix` did not exist before this session. It was created and
initialized as a Git repository on `main`.

## Compatibility findings

- **Wayland-only shell.** GNOME 50 has no X11 session, so `Alt+F2 r` is
  gone. A newly installed extension is discovered only after logging out and
  back in. After that, enabling and disabling work live.
- **Automated lifecycle testing works without touching the desktop.**
  `gnome-shell --headless --virtual-monitor` runs under `dbus-run-session`
  with a temporary HOME and `GSETTINGS_BACKEND=memory`. It starts in about a
  second. This is the basis of `tests/integration/extension_lifecycle.py`.
- **Extension state 6 (`INITIALIZED`)** is what GNOME 50 reports for an
  extension that is loaded but has never been enabled.
- **Shell `Eval` is unavailable** (unsafe mode is off and there is no CLI
  flag), so tests use a test-only probe extension that exposes D-Bus queries.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| No nested virtualization: the VM can't run KVM, so ISO boot and install tests would fall back to very slow software emulation | Enable "Virtualize Intel VT-x/EPT or AMD-V/RVI" in VMware's VM settings (CPU section), or run M8 boot tests as separate VMware VMs on the Windows host. |
| Every sudo action needs your password | The assistant prints the exact commands and you run them. Credentials are never stored or scripted. |
| `ubuntu-dock` conflicts with a JERONIX dock | The layout engine will disable `ubuntu-dock` only as part of an applied layout, with saved state and rollback (M5). It won't be force-removed. |
| Shell internals change every six months | Use only public `resource:///org/gnome/shell/...` modules, keep `shell-version` pinned to the tested release, and gate releases on the headless lifecycle test. |
| ISO builder support for 26.04 is unverified | Decide in M8. The preferred approach is remastering the official Ubuntu 26.04 desktop ISO: keep Canonical's signed shim and GRUB plus the stock installer, and add JERONIX packages from a local APT repository. This keeps Secure Boot working. Fallback: livecd-rootfs/live-build. Neither has been tested yet. |
| Repo exists only inside the VM | Add a Git remote, or back up the VM snapshot, before major work. |

## Implementation order

1. **M2 Foundation:** platform config, design tokens, first logo draft,
   architecture docs and test runner. *Done in this session.*
2. **M3 First extension:** `jeronix-quick-settings` (Stay Awake), with unit
   and headless lifecycle tests. *Done in this session.*
3. **M4 Desktop identity:** generate a Shell stylesheet from the tokens, add
   wallpapers and logo variants, and build a first layout (Pure, because it
   needs the fewest extensions).
4. **M5 Layout engine and Layout Studio:** versioned layout schema,
   validation, snapshot and rollback through GSettings, then the presets.
   The `jeronix-dock` extension is a dependency of Classic and Studio.
5. **M6 Applications:** System Information first (read-only, simplest),
   then Welcome and Settings.
6. **M7 Debian packages:** source packages per component, a meta-package,
   then lintian and install/remove tests in a disposable VM.
7. **M8 ISO:** remaster pipeline, checksums, then UEFI boot and install
   tests in fresh VMs.
8. **M9 Release readiness:** security, upgrade and licensing reviews, plus
   the hardware matrix.
