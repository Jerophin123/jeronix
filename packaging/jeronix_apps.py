# SPDX-License-Identifier: GPL-3.0-or-later
"""Stages the JERONIX applications and their shared data into a data
directory (/usr/share for the package, ~/.local/share for development).

Installed layout (see apps/jeronix_common/paths.py):
    <share>/jeronix/apps/<app>/...         application code
    <share>/jeronix/design/tokens.json     design tokens (app styling)
    <share>/jeronix/layouts/*.json         layouts
    <share>/jeronix/scripts/jeronix_layout.py
    <share>/jeronix/config/platform.json
    <share>/jeronix/branding/*.svg         logo lockups for the apps
    <share>/applications/io.jeronix.*.desktop
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
APP_PACKAGES = ("jeronix_common", "launcher", "layout_studio", "settings", "system_info", "welcome")
DESKTOP_IDS = ("io.jeronix.Launcher", "io.jeronix.LayoutStudio", "io.jeronix.Settings",
               "io.jeronix.SystemInfo", "io.jeronix.Welcome")
BRANDING = ("jeronix-lockup-on-dark.svg", "jeronix-lockup-on-light.svg", "jeronix-mark.svg")


def render_desktop(template, python, apps_dir):
    text = template.read_text(encoding="utf-8")
    return text.replace("@PYTHON@", python).replace("@APPS@", str(apps_dir))


def stage(share, python="/usr/bin/python3", apps_prefix=None, autostart_dir=None):
    """Copies apps and data under share. apps_prefix is the path the apps
    will have at run time (defaults to share, but the package build stages
    into a tree that is later installed at /usr/share). Returns the files
    and directories created, top-level first."""
    share = Path(share)
    runtime = Path(apps_prefix) if apps_prefix else share
    base = share / "jeronix"
    created = []

    def copy(src, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copyfile(src, dest)
        created.append(dest)

    for package in APP_PACKAGES:
        copy(APPS / package, base / "apps" / package)
    copy(ROOT / "design" / "tokens" / "tokens.json", base / "design" / "tokens.json")
    for layout in sorted((ROOT / "desktop" / "layouts").glob("*.json")):
        copy(layout, base / "layouts" / layout.name)
    copy(ROOT / "scripts" / "jeronix_layout.py", base / "scripts" / "jeronix_layout.py")
    copy(ROOT / "config" / "platform.json", base / "config" / "platform.json")
    for name in BRANDING:
        copy(ROOT / "design" / "icons" / name, base / "branding" / name)

    apps_dir = runtime / "jeronix" / "apps"
    for app_id in DESKTOP_IDS:
        dest = share / "applications" / f"{app_id}.desktop"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_desktop(APPS / "desktop" / f"{app_id}.desktop.in", python, apps_dir),
                        encoding="utf-8")
        created.append(dest)
    if autostart_dir is not None:
        dest = Path(autostart_dir) / "io.jeronix.Welcome.desktop"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_desktop(APPS / "desktop" / "io.jeronix.Welcome-autostart.desktop.in", python,
                                       apps_dir), encoding="utf-8")
        created.append(dest)
    return created


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Stage JERONIX apps into a data directory")
    ap.add_argument("share", type=Path)
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--autostart-dir", type=Path)
    args = ap.parse_args()
    for path in stage(args.share, args.python, autostart_dir=args.autostart_dir):
        print(path)
