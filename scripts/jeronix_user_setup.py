#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX per-user setup: the parts of the JERONIX look that live in a
user's home folder.

* every GTK 4 / libadwaita app: an @import of the JERONIX colors at the top
  of ~/.config/gtk-4.0/gtk.css (the rest of that file is left alone);
* the terminal: the JERONIX palette for Ptyxis, chosen for profiles that
  still use the stock Ubuntu or GNOME palette (never one picked by hand);
* the shell: the JERONIX prompt, sourced from ~/.bashrc;
* fastfetch: the JERONIX logo and layout (~/.config/fastfetch/config.jsonc,
  only if there is none, or it is JERONIX's own);
* snap apps whose menu entry names an icon file (App Center, Security
  Center, Firmware Updater): a copy of that entry in
  ~/.local/share/applications that names the JERONIX icon instead. It is
  rebuilt from the snap's current entry at every login, so it never goes
  stale, and removed when the snap is.

Each change is marked so it can be found and undone (--undo), and is applied
once per user (a stamp in ~/.local/state/jeronix): someone who removes a
line keeps it removed. The palette file is refreshed on every run, because
Ptyxis needs it to exist whenever a profile names it.

Run at login by /etc/xdg/autostart/io.jeronix.UserSetup.desktop (package),
or by hand for a development install:

    jeronix_user_setup.py [--data DIR] [--undo] [--force]
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SYSTEM_DATA = Path("/usr/share/jeronix")
STAMP_VERSION = "1"
GTK_MARK = "/* JERONIX colors (remove this line to opt out) */"
BASH_BEGIN = "# >>> JERONIX prompt >>>"
BASH_END = "# <<< JERONIX prompt <<<"
FASTFETCH_MARK = "// JERONIX fastfetch configuration"
PALETTE = "JERONIX"
# Palettes JERONIX replaces: the stock defaults, not anything chosen by hand.
STOCK_PALETTES = ("Ubuntu", "gnome", "")
PTYXIS = "org.gnome.Ptyxis"
SNAP_ENTRIES = Path("/var/lib/snapd/desktop/applications")
# Snap menu entries -> the JERONIX icon that replaces their icon file.
SNAP_ICONS = {
    "snap-store_snap-store.desktop": "jeronix-app-center",
    "desktop-security-center_desktop-security-center.desktop": "jeronix-security-center",
    "firmware-updater_firmware-updater.desktop": "jeronix-firmware-updater",
}
SNAP_MARK = "# JERONIX icon:"
PTYXIS_PROFILE = "org.gnome.Ptyxis.Profile"


def home():
    return Path.home()


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config")


def data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or home() / ".local" / "share")


def state_home():
    return Path(os.environ.get("XDG_STATE_HOME") or home() / ".local" / "state")


def stamp():
    return state_home() / "jeronix" / f"user-setup-v{STAMP_VERSION}"


def log(message):
    print(f"jeronix-user-setup: {message}", flush=True)


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".jeronix-tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


# -- GTK -------------------------------------------------------------------------

def gtk_line(data):
    css = (data / "gtk" / "gtk-4.0.css").resolve()
    return f'@import url("{css.as_uri()}"); {GTK_MARK}'


def gtk_apply(data):
    path = config_home() / "gtk-4.0" / "gtk.css"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [l for l in text.splitlines() if GTK_MARK not in l]
    write_atomic(path, "\n".join([gtk_line(data)] + lines) + "\n")
    log(f"GTK apps use the JERONIX colors ({path})")


def gtk_undo():
    path = config_home() / "gtk-4.0" / "gtk.css"
    if not path.exists():
        return
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if GTK_MARK not in l]
    if any(l.strip() for l in lines):
        write_atomic(path, "\n".join(lines) + "\n")
    else:
        path.unlink()
    log("GTK apps: JERONIX colors removed")


# -- terminal -----------------------------------------------------------------------

def palette_path():
    return data_home() / PTYXIS / "palettes" / f"{PALETTE}.palette"


def palette_install(data):
    source = data / "terminal" / f"{PALETTE}.palette"
    if source.is_file():
        write_atomic(palette_path(), source.read_text(encoding="utf-8"))


def gsettings(*args):
    try:
        r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def unquote(value):
    return value.strip("'") if value and value.startswith("'") else value


def ptyxis_profiles():
    """Ptyxis profile UUIDs, or [] if Ptyxis is not installed."""
    raw = gsettings("get", PTYXIS, "profile-uuids")
    if not raw or not raw.startswith("["):
        return []
    return [p.strip().strip("'") for p in raw.strip("[]").split(",") if p.strip().strip("'")]


def profile_path(uuid):
    return f"{PTYXIS_PROFILE}:/org/gnome/Ptyxis/Profiles/{uuid}/"


def terminal_apply(data):
    palette_install(data)
    for uuid in ptyxis_profiles():
        current = unquote(gsettings("get", profile_path(uuid), "palette"))
        if current in STOCK_PALETTES:
            gsettings("set", profile_path(uuid), "palette", f"'{PALETTE}'")
            # Report what is actually stored, not what was asked for.
            now = unquote(gsettings("get", profile_path(uuid), "palette"))
            if now == PALETTE:
                log(f"terminal profile {uuid}: {current or 'default'} palette -> {PALETTE}")
            else:
                log(f"terminal profile {uuid}: could not set the palette (still {now!r})")


def terminal_undo():
    for uuid in ptyxis_profiles():
        if unquote(gsettings("get", profile_path(uuid), "palette")) == PALETTE:
            gsettings("reset", profile_path(uuid), "palette")
            log(f"terminal profile {uuid}: palette reset")
    if palette_path().exists():
        palette_path().unlink()


# -- bash prompt ------------------------------------------------------------------

def bash_block(data):
    prompt = (data / "terminal" / "prompt.sh").resolve()
    return f'{BASH_BEGIN}\n[ -f "{prompt}" ] && . "{prompt}"\n{BASH_END}'


def strip_block(text):
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == BASH_BEGIN:
            skipping = True
            continue
        if line.strip() == BASH_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def bash_apply(data):
    path = home() / ".bashrc"
    if not path.exists():
        log("no ~/.bashrc; prompt not added")
        return
    lines = strip_block(path.read_text(encoding="utf-8"))
    write_atomic(path, "\n".join(lines + ["", bash_block(data)]) + "\n")
    log("bash uses the JERONIX prompt (new terminals)")


def bash_undo():
    path = home() / ".bashrc"
    if path.exists() and BASH_BEGIN in path.read_text(encoding="utf-8"):
        write_atomic(path, "\n".join(strip_block(path.read_text(encoding="utf-8"))) + "\n")
        log("bash prompt: JERONIX block removed")


# -- fastfetch ----------------------------------------------------------------------

def fastfetch_path():
    return config_home() / "fastfetch" / "config.jsonc"


def fastfetch_apply(data):
    path = fastfetch_path()
    if path.exists() and FASTFETCH_MARK not in path.read_text(encoding="utf-8"):
        log(f"{path} is your own; fastfetch left alone")
        return
    template = (data / "terminal" / "fastfetch.jsonc.in").read_text(encoding="utf-8")
    logo = (data / "terminal" / "fastfetch-logo.txt").resolve()
    write_atomic(path, template.replace("@LOGO@", str(logo)))
    log("fastfetch shows JERONIX")


def fastfetch_undo():
    path = fastfetch_path()
    if path.exists() and FASTFETCH_MARK in path.read_text(encoding="utf-8"):
        path.unlink()
        log("fastfetch: JERONIX configuration removed")


# -- snap app icons --------------------------------------------------------------

def snap_entry_path(desktop_id):
    return data_home() / "applications" / desktop_id


def is_ours(path):
    try:
        return path.read_text(encoding="utf-8").startswith(SNAP_MARK)
    except OSError:
        return False


def snap_icons_apply(source_dir=None):
    """Refreshes the JERONIX copies of snap menu entries (every login)."""
    source_dir = Path(source_dir or SNAP_ENTRIES)
    for desktop_id, icon in SNAP_ICONS.items():
        source, target = source_dir / desktop_id, snap_entry_path(desktop_id)
        if target.exists() and not is_ours(target):
            continue  # someone's own entry
        if not source.is_file():
            if target.exists():
                target.unlink()  # the snap is gone
            continue
        lines = [f"{SNAP_MARK} copy of {source}, rebuilt at every login"]
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.startswith("Icon="):
                line = f"Icon={icon}"
            lines.append(line)
        write_atomic(target, "\n".join(lines) + "\n")


def snap_icons_undo():
    for desktop_id in SNAP_ICONS:
        target = snap_entry_path(desktop_id)
        if is_ours(target):
            target.unlink()


# -- main -----------------------------------------------------------------------

def find_data(explicit=None):
    candidates = [Path(explicit)] if explicit else [data_home() / "jeronix", SYSTEM_DATA]
    for c in candidates:
        if (c / "terminal" / "prompt.sh").is_file() and (c / "gtk" / "gtk-4.0.css").is_file():
            return c
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Apply or undo the JERONIX look in your home folder")
    ap.add_argument("--data", help="JERONIX data folder (default: ~/.local/share/jeronix, then /usr/share/jeronix)")
    ap.add_argument("--undo", action="store_true", help="remove everything this setup added")
    ap.add_argument("--force", action="store_true", help="apply again even if it was applied before")
    args = ap.parse_args(argv)

    if args.undo:
        gtk_undo()
        terminal_undo()
        bash_undo()
        fastfetch_undo()
        snap_icons_undo()
        if stamp().exists():
            stamp().unlink()
        return 0

    data = find_data(args.data)
    if data is None:
        log("JERONIX data not found; nothing to do")
        return 1
    # Refreshed at every login: Ptyxis needs the palette file whenever a
    # profile names it, and snap entries change when snaps update.
    palette_install(data)
    try:
        snap_icons_apply()
    except OSError as e:
        log(f"snap icons failed: {e}")
    if stamp().exists() and not args.force:
        return 0
    for step in (gtk_apply, terminal_apply, bash_apply, fastfetch_apply):
        try:
            step(data)
        except OSError as e:  # one failing part must not stop the others
            log(f"{step.__name__} failed: {e}")
    stamp().parent.mkdir(parents=True, exist_ok=True)
    stamp().write_text(f"{data}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
