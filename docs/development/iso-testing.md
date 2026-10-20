# Testing the JERONIX ISO in a virtual machine

The builder checks the image's structure, but it can't boot it: the build VM
has no KVM. Boot and installation have to be tested in a separate VM. These
steps are for VMware Workstation on the Windows host. Hyper-V notes follow
at the end.

## 1. Copy the ISO and verify it

On the build VM the image is `out/iso/jeronix-26.04-x86_64.iso`, next to
`jeronix-26.04-x86_64.iso.sha256`. After copying both to Windows, check
the hash in PowerShell:

```powershell
Get-FileHash .\jeronix-26.04-x86_64.iso -Algorithm SHA256
Get-Content .\jeronix-26.04-x86_64.iso.sha256
```

The two values must be the same (case does not matter).

## 2. Create test VMs

Use **two** VMs so that each firmware type is tested:

| VM | Firmware | Secure Boot | Purpose |
| --- | --- | --- | --- |
| `jeronix-uefi` | UEFI | **on** | Main path: UEFI, Secure Boot, install |
| `jeronix-bios` | BIOS | n/a | Legacy BIOS boot |

In VMware: New Virtual Machine → Typical → *Installer disc image file* (the
ISO) → guest OS *Linux, Ubuntu 64-bit* → 25 GB disk, 4 GB RAM, 2 CPUs. Then,
before first power-on, open *VM Settings → Options → Advanced → Firmware
type* and choose UEFI with *Enable secure boot*, or BIOS. Turn on 3D
acceleration under *Display*.

## 3. Checklist

Record each result (pass/fail plus a note or screenshot).

**Boot (each VM)**
- [ ] The GRUB menu shows **"Try or Install JERONIX"**.
- [ ] UEFI VM: it boots with Secure Boot on. In the live session,
      `mokutil --sb-state` prints `SecureBoot enabled`.
- [ ] It reaches the live desktop (user `ubuntu`, no password).

**Live session**
- [ ] The charcoal panel and JERONIX wallpaper appear. `gnome-extensions list --enabled`
      includes `jeronix-shell-theme@jeronix` and `jeronix-quick-settings@jeronix`.
- [ ] Quick Settings shows **Stay Awake**. With it on, `gnome-session-inhibit --list`
      lists it.
- [ ] The dock hides until needed, the desktop has no icons, and the clock shows the weekday.
- [ ] `cat /etc/jeronix-release` and `ls /cdrom/jeronix` work.

**Installation (UEFI VM, then optionally BIOS)**
- [ ] The installer starts as **JERONIX Installer**: the JERONIX logo on the first page, "Try JERONIX" /
      "Install JERONIX", JERONIX blue buttons and JERONIX pictures on every page (light and dark).
- [ ] Its sources are labelled "JERONIX Desktop ...".
- [ ] While installing, the six JERONIX slides play (Welcome, Start, Everything at a glance, Control
      Center, A layout that fits, Built on Ubuntu).
- [ ] Closing the installer in the live session does not bring desktop icons or Ubuntu's dock back.
- [ ] Install with *Erase disk*, default choice, then reboot and remove the ISO.
- [ ] The installed system boots (UEFI VM: still with Secure Boot on).
- [ ] At the first login, **only** JERONIX Welcome opens (no "Welcome to Ubuntu"): style and accent,
      layout, privacy, essentials. It does not open again at the next login.
- [ ] After login, check the JERONIX theme, wallpaper and Stay Awake, and
      that `jeronix-layout plan /usr/share/jeronix/layouts/pure.json` runs.
- [ ] `sudo apt install /cdrom/jeronix/jeronix-desktop_*.deb` (with the ISO
      attached) succeeds, and afterwards `dpkg -S /etc/jeronix-release`
      names `jeronix-desktop`.
- [ ] `gnome-extensions disable jeronix-shell-theme@jeronix` returns the
      Ubuntu look immediately.
- [ ] Repeat the installation with the *Extended selection* (full Ubuntu
      Desktop source) if time allows.

**Check disc for defects** (GRUB → Try → the live system runs
`casper-md5check`, or select it if offered): no mismatches.

## 4. If something fails

- It doesn't boot at all: note the firmware type and the last message, and
  check whether the original Ubuntu 26.04.1 ISO boots in the same VM.
- The theme is missing in the live session: run
  `journalctl -b /usr/bin/gnome-shell | grep -i jeronix`.
- Send the build's `out/iso/*.manifest.json` and `build-*.log` with the report.

## Hyper-V

Generation 2 VM, Secure Boot template **"Microsoft UEFI Certificate
Authority"** (the default "Microsoft Windows" template rejects Linux
shims), and 4 GB of static memory. Generation 1 tests BIOS boot.
