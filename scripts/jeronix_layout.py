#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validates, applies and reverts JERONIX desktop layouts.

A layout is declarative data (desktop/layouts/*.json): a list of GSettings
values. There is no way to run commands from a layout. Only the schema/key
pairs in ALLOWED can be written, every value is checked against the
installed GSettings schema (type and range) before anything changes, and
extensions are never enabled or disabled.

    scripts/jeronix_layout.py validate desktop/layouts/pure.json
    scripts/jeronix_layout.py plan     desktop/layouts/pure.json   # dry run
    scripts/jeronix_layout.py apply    desktop/layouts/pure.json
    scripts/jeronix_layout.py snapshots
    scripts/jeronix_layout.py restore  [SNAPSHOT]                  # default: latest

`apply` first saves the current value of every key it will touch to
$XDG_STATE_HOME/jeronix/layout-snapshots/. `restore` puts those values back
(keys that were at their default are reset rather than written). Settings
take effect immediately; no logout is needed.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "config" / "platform.json"

LAYOUT_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1

# Every key a layout may write. Anything that can launch programs (custom
# keybindings, autostart, enabled-extensions) is deliberately absent.
ALLOWED = {
    "org.gnome.desktop.interface": {
        "color-scheme", "accent-color", "enable-hot-corners", "clock-show-weekday",
        "clock-show-seconds", "clock-format", "show-battery-percentage", "enable-animations",
    },
    "org.gnome.desktop.wm.preferences": {"button-layout", "focus-mode", "action-double-click-titlebar"},
    "org.gnome.mutter": {
        "overlay-key", "dynamic-workspaces", "workspaces-only-on-primary", "edge-tiling",
        "center-new-windows",
    },
    "org.gnome.desktop.background": {"picture-uri", "picture-uri-dark", "picture-options", "primary-color"},
    "org.gnome.desktop.screensaver": {"picture-uri"},
    "org.gnome.shell.extensions.dash-to-dock": {
        "dock-fixed", "autohide", "intellihide", "dock-position", "extend-height", "show-trash",
        "show-mounts", "dash-max-icon-size",
    },
    "org.gnome.shell.extensions.ding": {"show-home", "show-trash", "show-volumes"},
}

# Asset ids a layout may reference, relative to $XDG_DATA_HOME. They are
# installed by scripts/install-desktop-dev.sh (and later by packages).
ASSETS = {
    "wallpaper-dark": "backgrounds/jeronix/jeronix-dark.png",
    "wallpaper-light": "backgrounds/jeronix/jeronix-light.png",
}

ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
LAYOUT_KEYS = {"schema", "id", "name", "version", "description", "gnome_shell",
               "settings", "extensions", "limitations"}
SETTING_KEYS = {"schema", "key", "value", "reason", "optional"}


class LayoutError(Exception):
    pass


def data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def snapshot_dir():
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return state / "jeronix" / "layout-snapshots"


def data_dirs():
    """User data dir first, then the system ones (XDG Base Directory order)."""
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [data_home()] + [Path(d) for d in system.split(":") if d]


def asset_path(asset_id, data_dir=None):
    """Where an asset lives. With data_dir (used when building images) that
    directory is assumed; otherwise the first installed copy wins, falling
    back to the user data dir."""
    if asset_id not in ASSETS:
        raise LayoutError(f"unknown asset {asset_id!r} (known: {', '.join(sorted(ASSETS))})")
    if data_dir is not None:
        return Path(data_dir) / ASSETS[asset_id]
    for base in data_dirs():
        if (base / ASSETS[asset_id]).is_file():
            return base / ASSETS[asset_id]
    return data_home() / ASSETS[asset_id]


def asset_uri(asset_id, data_dir=None):
    return asset_path(asset_id, data_dir).as_uri()


# -- structural validation (no GSettings needed) ----------------------------

def check_structure(layout):
    """Returns a list of problems with the layout document itself."""
    if not isinstance(layout, dict):
        return ["layout must be a JSON object"]
    problems = []
    unknown = set(layout) - LAYOUT_KEYS
    missing = {"schema", "id", "name", "version", "description", "gnome_shell", "settings"} - set(layout)
    problems += [f"unknown field {k!r}" for k in sorted(unknown)]
    problems += [f"missing field {k!r}" for k in sorted(missing)]
    if problems:
        return problems
    if layout["schema"] != LAYOUT_SCHEMA_VERSION:
        problems.append(f"schema must be {LAYOUT_SCHEMA_VERSION}")
    if not isinstance(layout["id"], str) or not ID.match(layout["id"]):
        problems.append("id must be a lowercase slug")
    if not isinstance(layout["version"], str) or not SEMVER.match(layout["version"]):
        problems.append("version must be semver")
    supported = json.loads(PLATFORM.read_text(encoding="utf-8"))["gnome_shell"]["supported_versions"]
    if not isinstance(layout["gnome_shell"], list) or not layout["gnome_shell"] \
            or not set(layout["gnome_shell"]) <= set(supported):
        problems.append(f"gnome_shell must be a non-empty subset of {supported} (config/platform.json)")
    if not isinstance(layout["settings"], list) or not layout["settings"]:
        return problems + ["settings must be a non-empty list"]
    seen = set()
    for n, s in enumerate(layout["settings"]):
        where = f"settings[{n}]"
        if not isinstance(s, dict):
            problems.append(f"{where} must be an object")
            continue
        problems += [f"{where}: unknown field {k!r}" for k in sorted(set(s) - SETTING_KEYS)]
        problems += [f"{where}: missing field {k!r}" for k in ("schema", "key", "value", "reason") if k not in s]
        if not {"schema", "key", "value"} <= set(s):
            continue
        where = f"{where} {s['schema']} {s['key']}"
        if s["key"] not in ALLOWED.get(s["schema"], ()):
            problems.append(f"{where}: not an allowed layout setting")
        if (s["schema"], s["key"]) in seen:
            problems.append(f"{where}: duplicate")
        seen.add((s["schema"], s["key"]))
        if not isinstance(s.get("optional", False), bool):
            problems.append(f"{where}: optional must be true or false")
        value = s["value"]
        if isinstance(value, dict):
            if set(value) != {"asset"} or value["asset"] not in ASSETS:
                problems.append(f"{where}: object values must be {{\"asset\": one of {sorted(ASSETS)}}}")
        elif not isinstance(value, (bool, int, float, str, list)):
            problems.append(f"{where}: unsupported value type")
    for ext in layout.get("extensions", {}).get("recommended", []):
        if not isinstance(ext, dict) or set(ext) != {"uuid", "reason"}:
            problems.append("extensions.recommended entries need exactly uuid and reason")
    return problems


def load_layout(path):
    try:
        layout = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LayoutError(f"cannot read {path}: {e}") from e
    problems = check_structure(layout)
    if problems:
        raise LayoutError(f"{path} is invalid:\n  " + "\n  ".join(problems))
    return layout


# -- GSettings ---------------------------------------------------------------

def _gio():
    from gi.repository import Gio, GLib
    return Gio, GLib


def schema_key(schema_id, key):
    """(SettingsSchema, SettingsSchemaKey) or None if the schema isn't installed."""
    Gio, _ = _gio()
    schema = Gio.SettingsSchemaSource.get_default().lookup(schema_id, True)
    if schema is None:
        return None
    if not schema.has_key(key):
        raise LayoutError(f"{schema_id} has no key {key!r}")
    return schema, schema.get_key(key)


def to_variant(value, key):
    """Converts a JSON value to a GVariant of the key's type, checking its range."""
    _, GLib = _gio()
    vtype = key.get_value_type().dup_string()
    try:
        if vtype == "b" and isinstance(value, bool):
            variant = GLib.Variant("b", value)
        elif vtype in ("i", "u") and isinstance(value, int) and not isinstance(value, bool):
            variant = GLib.Variant(vtype, value)
        elif vtype == "d" and isinstance(value, (int, float)) and not isinstance(value, bool):
            variant = GLib.Variant("d", float(value))
        elif vtype == "s" and isinstance(value, str):
            variant = GLib.Variant("s", value)
        elif vtype == "as" and isinstance(value, list) and all(isinstance(v, str) for v in value):
            variant = GLib.Variant("as", value)
        else:
            raise LayoutError(f"value {value!r} does not fit GSettings type {vtype!r}")
    except (TypeError, OverflowError) as e:
        raise LayoutError(f"value {value!r}: {e}") from e
    if not key.range_check(variant):
        raise LayoutError(f"value {value!r} is outside the allowed range")
    return variant


def resolve(layout, need_assets=True, data_dir=None):
    """Checks every setting against installed schemas.

    Returns (changes, skipped): changes are dicts with schema, key, variant;
    skipped are optional settings whose schema is not installed. data_dir
    pins where assets will live (for image builds, e.g. /usr/share).
    """
    changes, skipped, problems = [], [], []
    for s in layout["settings"]:
        name = f"{s['schema']} {s['key']}"
        try:
            found = schema_key(s["schema"], s["key"])
            if found is None:
                if s.get("optional"):
                    skipped.append(name)
                    continue
                raise LayoutError(f"schema {s['schema']} is not installed")
            value = s["value"]
            if isinstance(value, dict):
                path = asset_path(value["asset"], data_dir)
                value = path.as_uri()
                if need_assets and not path.is_file():
                    raise LayoutError(f"asset {path} is missing; run scripts/install-desktop-dev.sh first")
            changes.append({"schema": s["schema"], "key": s["key"], "variant": to_variant(value, found[1])})
        except LayoutError as e:
            problems.append(f"{name}: {e}")
    if problems:
        raise LayoutError("layout does not fit this system:\n  " + "\n  ".join(problems))
    return changes, skipped


def current(schema_id, key):
    """(user_value_text_or_None, effective_value_text)."""
    Gio, _ = _gio()
    settings = Gio.Settings.new(schema_id)
    user = settings.get_user_value(key)
    return (user.print_(False) if user is not None else None), settings.get_value(key).print_(False)


# -- commands ------------------------------------------------------------------

def take_snapshot(layout, changes):
    entries = []
    for c in changes:
        user, _ = current(c["schema"], c["key"])
        entries.append({"schema": c["schema"], "key": c["key"], "user_value": user})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snap = {"schema": SNAPSHOT_SCHEMA_VERSION, "layout": layout["id"], "layout_version": layout["version"],
            "created": stamp, "entries": entries}
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stamp}-{layout['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def write_values(changes):
    Gio, _ = _gio()
    for c in changes:
        settings = Gio.Settings.new(c["schema"])
        if not settings.set_value(c["key"], c["variant"]):
            raise LayoutError(f"{c['schema']} {c['key']} is not writable")
    Gio.Settings.sync()


def apply(path, out=print):
    layout = load_layout(path)
    changes, skipped = resolve(layout)
    snap = take_snapshot(layout, changes)
    try:
        write_values(changes)
    except Exception:
        restore(snap, out=lambda *_: None)
        raise
    out(f"applied layout {layout['name']} {layout['version']}: {len(changes)} settings")
    for name in skipped:
        out(f"  skipped (schema not installed): {name}")
    for ext in layout.get("extensions", {}).get("recommended", []):
        out(f"  recommended extension (not enabled automatically): {ext['uuid']}")
    out(f"previous values saved to {snap}")
    out(f"undo with: scripts/jeronix_layout.py restore {snap}")
    return snap


def plan(path, out=print):
    layout = load_layout(path)
    changes, skipped = resolve(layout, need_assets=False)
    out(f"layout {layout['name']} {layout['version']} would change:")
    for c in changes:
        _, effective = current(c["schema"], c["key"])
        new = c["variant"].print_(False)
        mark = " " if effective == new else "*"
        out(f" {mark} {c['schema']} {c['key']}: {effective} -> {new}")
    for name in skipped:
        out(f"   skipped (schema not installed): {name}")
    return changes


def load_snapshot(path):
    try:
        snap = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LayoutError(f"cannot read snapshot {path}: {e}") from e
    if not isinstance(snap, dict) or snap.get("schema") != SNAPSHOT_SCHEMA_VERSION \
            or not isinstance(snap.get("entries"), list):
        raise LayoutError(f"{path} is not a JERONIX layout snapshot")
    for e in snap["entries"]:
        if not isinstance(e, dict) or set(e) != {"schema", "key", "user_value"} \
                or e["key"] not in ALLOWED.get(e["schema"], ()):
            raise LayoutError(f"{path}: entry {e!r} is not an allowed layout setting")
    return snap


def list_snapshots():
    directory = snapshot_dir()
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def restore(path=None, out=print):
    Gio, GLib = _gio()
    if path is None:
        snaps = list_snapshots()
        if not snaps:
            raise LayoutError(f"no snapshots in {snapshot_dir()}")
        path = snaps[-1]
    snap = load_snapshot(path)
    for e in snap["entries"]:
        found = schema_key(e["schema"], e["key"])
        if found is None:
            continue
        settings = Gio.Settings.new(e["schema"])
        if e["user_value"] is None:
            settings.reset(e["key"])
        else:
            try:
                variant = GLib.Variant.parse(found[1].get_value_type(), e["user_value"], None, None)
            except GLib.Error as err:
                raise LayoutError(f"{e['schema']} {e['key']}: bad saved value: {err.message}") from err
            settings.set_value(e["key"], variant)
    Gio.Settings.sync()
    out(f"restored {len(snap['entries'])} settings from {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate, apply and revert JERONIX layouts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "plan", "apply"):
        sub.add_parser(name).add_argument("layout", type=Path)
    sub.add_parser("snapshots")
    sub.add_parser("restore").add_argument("snapshot", type=Path, nargs="?")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "validate":
            layout = load_layout(args.layout)
            changes, skipped = resolve(layout, need_assets=False)
            print(f"{args.layout}: valid ({len(changes)} settings, {len(skipped)} optional skipped)")
        elif args.cmd == "plan":
            plan(args.layout)
        elif args.cmd == "apply":
            apply(args.layout)
        elif args.cmd == "snapshots":
            for p in list_snapshots():
                print(p)
        elif args.cmd == "restore":
            restore(args.snapshot)
    except LayoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
