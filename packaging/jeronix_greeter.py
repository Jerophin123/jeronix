#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the JERONIX login screen theme (the GDM greeter's gresource).

GNOME Shell's login mode loads gdm.css from the gdm-theme.gresource
alternative. JERONIX's greeter theme is GNOME's own default theme resource
(not Ubuntu's Yaru one) with the rendered JERONIX shell stylesheet and a few
greeter-only rules appended to gdm.css, and the JERONIX wallpaper as the
login background. Everything else in the resource is GNOME's, unchanged.

The package registers it with update-alternatives above Yaru, so removing
the package gives Ubuntu's greeter back automatically.

    jeronix_greeter.py build OUT.gresource --css RENDERED.css --background WALLPAPER.png
    jeronix_greeter.py install TARGET.gresource --css RENDERED.css --background WALLPAPER.png

install (used by the package at install time, so the theme always matches
the installed GNOME Shell) builds into a temporary folder, checks the new
gdm.css with GNOME Shell's own CSS parser (St), and only then moves the file
into place. If anything fails, the old file (or none) stays, so a broken
stylesheet can never reach the login screen.
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Loads stylesheets with St, GNOME Shell's CSS engine; prints "parsed" or an error.
CHECK_JS = """
const {Gio, St} = imports.gi;
for (const path of ARGV) {
    try {
        print(new St.Theme().load_stylesheet(Gio.File.new_for_path(path)) ? 'parsed' : 'failed');
    } catch (e) {
        print(`error: ${e.message}`);
    }
}
"""
from xml.sax.saxutils import escape

PREFIX = "/org/gnome/shell/theme"
BASE = Path("/usr/share/gnome-shell/gnome-shell-theme.gresource")
BACKGROUND = "jeronix-login-background.png"

# Only on the login screen: the wallpaper behind the user list and prompt.
GREETER_CSS = f"""
/* ---- JERONIX login screen (packaging/jeronix_greeter.py) ---------------- */
#lockDialogGroup {{
  background-color: #121722;
  background-image: url("resource://{PREFIX}/{BACKGROUND}");
  background-size: cover;
  background-position: center;
}}

.login-dialog-logo-bin {{
  padding: 24px 0;
}}
"""


def resources(gresource):
    """The paths inside a compiled gresource."""
    out = subprocess.run(["gresource", "list", str(gresource)], capture_output=True, text=True, check=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def extract(gresource, path):
    return subprocess.run(["gresource", "extract", str(gresource), path], capture_output=True, check=True).stdout


def build(out, css, background, base=BASE):
    """Writes the greeter gresource to out; returns the resource paths in it."""
    paths = resources(base)
    if f"{PREFIX}/gdm.css" not in paths:
        raise SystemExit(f"{base} has no {PREFIX}/gdm.css; unexpected GNOME Shell theme layout")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        names = []
        for path in paths:
            if not path.startswith(PREFIX + "/"):
                raise SystemExit(f"unexpected resource outside {PREFIX}: {path}")
            name = path[len(PREFIX) + 1:]
            data = extract(base, path)
            if name == "gdm.css":
                data = data + b"\n" + css.encode("utf-8") + GREETER_CSS.encode("utf-8")
            (src / name).parent.mkdir(parents=True, exist_ok=True)
            (src / name).write_bytes(data)
            names.append(name)
        shutil.copyfile(background, src / BACKGROUND)
        names.append(BACKGROUND)
        files = "\n".join(f"    <file>{escape(n)}</file>" for n in sorted(names))
        (src / "theme.gresource.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<gresources>\n  <gresource prefix="{PREFIX}">\n'
            f"{files}\n  </gresource>\n</gresources>\n", encoding="utf-8")
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["glib-compile-resources", "--sourcedir", str(src), "--target", str(out),
                        str(src / "theme.gresource.xml")], check=True)
    built = resources(out)
    expected = sorted(f"{PREFIX}/{n}" for n in names)
    if sorted(built) != expected:
        raise SystemExit(f"greeter resource is incomplete: {sorted(set(expected) - set(built))}")
    return built


def shell_libraries():
    """Directories holding GNOME Shell's and Mutter's private typelibs and libraries."""
    dirs = [d for d in ("/usr/lib/gnome-shell", "/usr/lib64/gnome-shell") if os.path.isdir(d)]
    dirs += sorted(glob.glob("/usr/lib/*/mutter-*") + glob.glob("/usr/lib/mutter-*") + glob.glob("/usr/lib64/mutter-*"))
    return dirs


def check_css(path):
    """None if St parses the stylesheet, else the reason it does not."""
    gjs = shutil.which("gjs")
    libs = shell_libraries()
    if not gjs or not libs:
        return "gjs or GNOME Shell's libraries are missing"
    env = dict(os.environ, GI_TYPELIB_PATH=":".join(libs), LD_LIBRARY_PATH=":".join(libs))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as script:
        script.write(CHECK_JS)
    try:
        r = subprocess.run([gjs, script.name, str(path)], capture_output=True, text=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    finally:
        os.unlink(script.name)
    out = r.stdout.strip().splitlines()
    return None if out == ["parsed"] else (r.stdout + r.stderr).strip() or "St did not parse it"


def install(target, css, background, base=BASE):
    """Builds, checks and atomically installs the greeter theme at target."""
    target = Path(target)
    with tempfile.TemporaryDirectory() as tmp:
        built = Path(tmp) / "gnome-shell-theme.gresource"
        build(built, css, background, base)
        gdm = Path(tmp) / "gdm.css"
        gdm.write_bytes(extract(built, f"{PREFIX}/gdm.css"))
        problem = check_css(gdm)
        if problem:
            raise SystemExit(f"the login screen stylesheet did not pass GNOME Shell's parser: {problem}")
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.name + ".new")
        shutil.copyfile(built, staged)
        staged.chmod(0o644)
        os.replace(staged, target)
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build or install the JERONIX login screen theme")
    ap.add_argument("command", choices=("build", "install"))
    ap.add_argument("out", type=Path)
    ap.add_argument("--css", type=Path, required=True, help="the rendered JERONIX shell stylesheet (dark)")
    ap.add_argument("--background", type=Path, required=True)
    ap.add_argument("--base", type=Path, default=BASE)
    args = ap.parse_args(argv)
    css = args.css.read_text(encoding="utf-8")
    if args.command == "install":
        print(install(args.out, css, args.background, args.base))
    else:
        for path in build(args.out, css, args.background, args.base):
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
