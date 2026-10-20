# JERONIX system identity

What the `jeronix-desktop` package changes outside the desktop session, and
how each change is undone. Built by `packaging/jeronix_payload.py deb`;
installed with `sudo apt install ./jeronix-desktop_*.deb`.

## What people see

| Where | Before | With JERONIX | How |
| --- | --- | --- | --- |
| Login screen | Yaru theme, Ubuntu logo | JERONIX theme on the JERONIX wallpaper, JERONIX logo, blue accent | `gdm-theme.gresource` alternative (priority 50, above Yaru's 15), built at install time by `packaging/jeronix_greeter.py` and checked with GNOME Shell's CSS parser first; `/usr/share/gdm/dconf/95-jeronix-settings` |
| Lock screen | Yaru | Large clock, pill password field, blue focus | `jeronix-shell-theme@jeronix` also runs in the `unlock-dialog` session mode |
| Log-out and power dialogs | Yaru | JERONIX dialog style | shell theme |
| Boot splash | firmware logo (bgrt) | the J on graphite with a spinner | `default.plymouth` alternative (priority 150), `update-initramfs -u` |
| Text boot splash (no graphics yet, e.g. a disk password prompt) | "Ubuntu 26.04" on purple | "JERONIX 26.04" on graphite, blue progress dots | `text.plymouth` alternative `jeronix-text` (priority 150, above `ubuntu-text`'s 50), Ubuntu's `ubuntu-text` plugin |
| Boot menu, About, `hostnamectl`, fastfetch | Ubuntu 26.04.1 LTS | JERONIX 26.04 | `/usr/lib/os-release` (`NAME`, `PRETTY_NAME`), `update-grub` |
| Terminal and SSH logins | `Ubuntu 26.04.1 LTS`, Ubuntu help links, Ubuntu Pro messages | `JERONIX 26.04` | `/etc/issue`, `/etc/issue.net`, `/etc/lsb-release` (`DISTRIB_DESCRIPTION`), help and Ubuntu Pro messages moved aside |
| Session name at login | Ubuntu | JERONIX | the session file, same command line |
| Every GTK 4 app | Ubuntu colors | JERONIX graphite and blue | `@import` at the top of `~/.config/gtk-4.0/gtk.css` |
| Terminal (Ptyxis) | Ubuntu palette | JERONIX palette, JERONIX prompt | palette file and default, `~/.bashrc` block |
| fastfetch | Ubuntu logo | the JERONIX J | `/etc/xdg/fastfetch/config.jsonc` and `~/.config/fastfetch/config.jsonc` |

## What stays Ubuntu, on purpose

`ID=ubuntu` in `/etc/os-release` and `DISTRIB_ID=Ubuntu` in
`/etc/lsb-release` are machine identifiers, not names: apt tooling, the Ubuntu
Pro client, `add-apt-repository` and many third-party installers check them,
and changing them can break updates. `UBUNTU_CODENAME` stays for the same
reason. The package archive, App Center, Software Updater and Security Center
are Ubuntu's and keep working unchanged.

## How it is undone

Files of other packages are never overwritten. `preinst` moves each one aside
with `dpkg-divert --rename` (to `<file>.ubuntu`), and `postrm` moves it back
when the package is removed; `prerm` removes the login screen and boot splash
alternatives. Optional steps (login screen, boot splash, boot menu) print a
warning and keep the current state if they fail, so installation never leaves
a broken login or boot.

    sudo apt remove jeronix-desktop      # everything above returns to Ubuntu's
    python3 /usr/share/jeronix/scripts/jeronix_user_setup.py --undo   # your home folder

The per-user part (`scripts/jeronix_user_setup.py`) runs once per user at
login from `/etc/xdg/autostart/io.jeronix.UserSetup.desktop`. Its changes are
marked lines, never whole files: someone's own `gtk.css`, fastfetch
configuration and terminal palette choice are kept.

If the login screen ever needs to be reset by hand, from a text console:

    sudo update-alternatives --auto gdm-theme.gresource

## Not covered

* The ISO: its builder layers JERONIX's files over the Ubuntu image and never
  replaces the image's own files or runs package scripts, so an ISO install
  shows Ubuntu at login and boot until `jeronix-desktop` is reinstalled with
  apt. Running the package scripts in the image is the next step for
  `build/iso/`.
* The installer, which is Ubuntu's.
* GTK 3 apps keep Adwaita's own colors (its accent is blue already).
