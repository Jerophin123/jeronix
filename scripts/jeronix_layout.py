#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validates, applies and reverts JERONIX desktop layouts.

A layout is declarative data (desktop/layouts/*.json): GSettings values plus
which JERONIX or Ubuntu shell extensions to switch on or off. There is no
way to run commands from a layout:

* Only the schema/key pairs in ALLOWED can be written, and every value is
  checked against the installed GSettings schema (type and range) before
  anything changes. JERONIX extension settings are read from the schemas
  that ship inside those extensions.
* Only the extensions in SWITCHABLE can be enabled or disabled, an
  extension is enabled only if it is installed, and the change is made by
  editing org.gnome.shell enabled-extensions/disabled-extensions, which is
  snapshotted like any other key.

    scripts/jeronix_layout.py validate desktop/layouts/pure.json
    scripts/jeronix_layout.py plan     desktop/layouts/pure.json   # dry run
    scripts/jeronix_layout.py apply    desktop/layouts/pure.json
    scripts/jeronix_layout.py snapshots
    scripts/jeronix_layout.py restore  [SNAPSHOT]                  # default: latest

`apply` first saves the current value of every key it will touch to
$XDG_STATE_HOME/jeronix/layout-snapshots/. `restore` puts those values back
(keys that were at their default are reset rather than written). Settings
and extension switches take effect immediately; no logout is needed.
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

LAYOUT_SCHEMA_VERSION = 2
SNAPSHOT_SCHEMA_VERSION = 2

# Every key a layout may write. Nothing that can launch programs (custom
# keybindings with commands, autostart) is here; the extension lists are
# handled separately and only for SWITCHABLE extensions.
WORKSPACE_KEYS = {f"{action}-{n}" for action in ("switch-to-workspace", "move-to-workspace") for n in range(1, 5)}
ALLOWED = {
    "org.gnome.desktop.interface": {
        "color-scheme", "accent-color", "enable-hot-corners", "clock-show-weekday",
        "clock-show-seconds", "clock-format", "show-battery-percentage", "enable-animations", "icon-theme",
    },
    "org.gnome.desktop.wm.preferences": {"button-layout", "focus-mode", "action-double-click-titlebar",
                                         "num-workspaces"},
    "org.gnome.desktop.wm.keybindings": WORKSPACE_KEYS,
    "org.gnome.shell.keybindings": {f"switch-to-application-{n}" for n in range(1, 5)},
    "org.gnome.shell.app-switcher": {"current-workspace-only"},
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
    "org.gnome.shell.extensions.jeronix-dock": {
        "position", "behavior", "icon-size", "show-running", "show-apps-button", "show-previews",
        "show-start-button", "show-search-button", "magnify",
    },
    "org.gnome.shell.extensions.jeronix-panel": {
        "show-menu-label", "show-workspaces", "show-window-context", "hide-activities",
    },
}

# Schemas that ship inside a GNOME Shell extension (schemas/gschemas.compiled).
EXTENSION_SCHEMAS = {
    "org.gnome.shell.extensions.jeronix-dock": "jeronix-dock@jeronix",
    "org.gnome.shell.extensions.jeronix-panel": "jeronix-panel@jeronix",
}

# Extensions a layout may switch on or off.
SWITCHABLE = frozenset({
    "jeronix-shell-theme@jeronix", "jeronix-panel@jeronix", "jeronix-dock@jeronix",
    "jeronix-quick-settings@jeronix", "ubuntu-dock@ubuntu.com", "ding@rastersoft.com",
})
EXTENSION_LIST_KEYS = ("enabled-extensions", "disabled-extensions")

# Asset ids a layout may reference, relative to a data directory. They are
# installed by scripts/install-desktop-dev.sh or the jeronix-desktop package.
ASSETS = {
    "wallpaper-dark": "backgrounds/jeronix/jeronix-dark.png",
    "wallpaper-light": "backgrounds/jeronix/jeronix-light.png",
}

ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
LAYOUT_KEYS = {"schema", "id", "name", "version", "description", "gnome_shell",
               "settings", "extensions", "limitations", "summary"}
SETTING_KEYS = {"schema", "key", "value", "reason", "optional"}
EXTENSION_KEYS = {"enable", "disable", "recommended"}


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


def extension_dir(uuid):
    """Installed directory of an extension, or None.

    $JERONIX_EXTENSION_DIRS (colon-separated directories holding <uuid>/)
    is searched first; image builds use it to point at built extensions."""
    extra = [Path(d) for d in os.environ.get("JERONIX_EXTENSION_DIRS", "").split(":") if d]
    for base in extra + [d / "gnome-shell" / "extensions" for d in data_dirs()]:
        if (base / uuid / "metadata.json").is_file():
            return base / uuid
    return None


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


def icon_theme_installed(name):
    """Whether an icon theme exists (an unknown theme makes GTK fall back
    to hicolor, which would look broken)."""
    if not isinstance(name, str) or "/" in name or name.startswith("."):
        return False
    bases = [Path.home() / ".icons"] + [d / "icons" for d in data_dirs()]
    return any((b / name / "index.theme").is_file() for b in bases)


# -- structural validation (no GSettings needed) ----------------------------

def _check_extensions(ext):
    problems = []
    if not isinstance(ext, dict):
        return ["extensions must be an object"]
    problems += [f"extensions: unknown field {k!r}" for k in sorted(set(ext) - EXTENSION_KEYS)]
    for field in ("enable", "disable"):
        uuids = ext.get(field, [])
        if not isinstance(uuids, list) or not all(isinstance(u, str) for u in uuids):
            problems.append(f"extensions.{field} must be a list of UUIDs")
            continue
        problems += [f"extensions.{field}: {u} may not be switched by a layout"
                     for u in uuids if u not in SWITCHABLE]
    if set(ext.get("enable", [])) & set(ext.get("disable", [])):
        problems.append("extensions: the same UUID is both enabled and disabled")
    for rec in ext.get("recommended", []):
        if not isinstance(rec, dict) or set(rec) != {"uuid", "reason"}:
            problems.append("extensions.recommended entries need exactly uuid and reason")
    return problems


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
    if "extensions" in layout:
        problems += _check_extensions(layout["extensions"])
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


def list_layouts(directory):
    """(path, layout) for every valid layout in a directory, by name."""
    found = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            found.append((path, load_layout(path)))
        except LayoutError:
            continue
    return found


# -- GSettings ---------------------------------------------------------------

def _gio():
    from gi.repository import Gio, GLib
    return Gio, GLib


def lookup_schema(schema_id):
    """SettingsSchema for schema_id, or None if not installed."""
    Gio, _ = _gio()
    default = Gio.SettingsSchemaSource.get_default()
    if schema_id in EXTENSION_SCHEMAS:
        ext = extension_dir(EXTENSION_SCHEMAS[schema_id])
        if ext is None or not (ext / "schemas" / "gschemas.compiled").is_file():
            return None
        source = Gio.SettingsSchemaSource.new_from_directory(str(ext / "schemas"), default, False)
        return source.lookup(schema_id, False)
    return default.lookup(schema_id, True) if default else None


def settings_for(schema_id):
    Gio, _ = _gio()
    schema = lookup_schema(schema_id)
    if schema is None:
        raise LayoutError(f"schema {schema_id} is not installed")
    return Gio.Settings.new_full(schema, None, None)


def schema_key(schema_id, key):
    """(SettingsSchema, SettingsSchemaKey) or None if the schema isn't installed."""
    schema = lookup_schema(schema_id)
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
                hint = " (install the JERONIX extensions first)" if s["schema"] in EXTENSION_SCHEMAS else ""
                raise LayoutError(f"schema {s['schema']} is not installed{hint}")
            value = s["value"]
            if isinstance(value, dict):
                path = asset_path(value["asset"], data_dir)
                value = path.as_uri()
                if need_assets and not path.is_file():
                    raise LayoutError(f"asset {path} is missing; run scripts/install-desktop-dev.sh first")
            if (s["schema"], s["key"]) == ("org.gnome.desktop.interface", "icon-theme") and need_assets \
                    and not icon_theme_installed(value):
                raise LayoutError(f"icon theme {value!r} is not installed")
            changes.append({"schema": s["schema"], "key": s["key"], "variant": to_variant(value, found[1])})
        except LayoutError as e:
            problems.append(f"{name}: {e}")
    ext = layout.get("extensions", {})
    for uuid in ext.get("enable", []):
        if extension_dir(uuid) is None:
            problems.append(f"extension {uuid} is not installed, so the layout cannot enable it")
    if problems:
        raise LayoutError("layout does not fit this system:\n  " + "\n  ".join(problems))
    return changes, skipped


def current(schema_id, key):
    """(user_value_text_or_None, effective_value_text)."""
    settings = settings_for(schema_id)
    user = settings.get_user_value(key)
    return (user.print_(False) if user is not None else None), settings.get_value(key).print_(False)


# -- extension lists -----------------------------------------------------------

def extension_lists():
    shell = settings_for("org.gnome.shell")
    return list(shell.get_strv("enabled-extensions")), list(shell.get_strv("disabled-extensions"))


def switched_lists(layout, enabled, disabled):
    """New (enabled, disabled) lists after the layout's switches; order kept."""
    ext = layout.get("extensions", {})
    on, off = set(ext.get("enable", [])), set(ext.get("disable", []))
    new_enabled = [u for u in enabled if u not in off] + [u for u in ext.get("enable", []) if u not in enabled]
    new_disabled = [u for u in disabled if u not in on] + [u for u in ext.get("disable", []) if u not in disabled]
    return new_enabled, new_disabled


def describe(path, data_dir=None):
    """Structured dry run: what apply would change.

    Returns {"layout", "settings": [...], "extensions": [...], "skipped": [...]}.
    """
    layout = load_layout(path)
    changes, skipped = resolve(layout, need_assets=False, data_dir=data_dir)
    rows = []
    for c in changes:
        _, effective = current(c["schema"], c["key"])
        new = c["variant"].print_(False)
        rows.append({"schema": c["schema"], "key": c["key"], "current": effective, "new": new,
                     "changed": effective != new})
    enabled, disabled = extension_lists()
    ext_rows = []
    for action in ("enable", "disable"):
        for uuid in layout.get("extensions", {}).get(action, []):
            already = (uuid in enabled and uuid not in disabled) if action == "enable" else uuid in disabled
            ext_rows.append({"uuid": uuid, "action": action, "changed": not already})
    return {"layout": layout, "settings": rows, "extensions": ext_rows, "skipped": skipped}


# -- commands ------------------------------------------------------------------

def take_snapshot(layout, changes):
    entries = []
    for c in changes:
        user, _ = current(c["schema"], c["key"])
        entries.append({"schema": c["schema"], "key": c["key"], "user_value": user})
    if layout.get("extensions", {}).get("enable") or layout.get("extensions", {}).get("disable"):
        for key in EXTENSION_LIST_KEYS:
            user, _ = current("org.gnome.shell", key)
            entries.append({"schema": "org.gnome.shell", "key": key, "user_value": user})
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
        if not settings_for(c["schema"]).set_value(c["key"], c["variant"]):
            raise LayoutError(f"{c['schema']} {c['key']} is not writable")
    Gio.Settings.sync()


def _shell_extension_states(uuids):
    """{uuid: state} from a running GNOME Shell, or None without one."""
    Gio, GLib = _gio()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        states = {}
        for uuid in uuids:
            reply = bus.call_sync("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions",
                                  "GetExtensionInfo", GLib.Variant("(s)", (uuid,)), None,
                                  Gio.DBusCallFlags.NONE, 2000, None)
            states[uuid] = int(reply.unpack()[0].get("state", 0))
        return states
    except GLib.Error:
        return None


def _wait_until_stopped(uuids, timeout=8.0):
    """Waits until a running shell has stopped these extensions.

    GNOME Shell 50 handles extension-list changes asynchronously; writing
    the second list while the first change is still being processed makes
    two passes overlap and enable extensions twice. Without a shell (tests,
    image builds) this returns at once."""
    import time
    deadline = time.monotonic() + timeout
    while uuids:
        states = _shell_extension_states(uuids)
        if states is None or all(s != 1 for s in states.values()) or time.monotonic() > deadline:
            return
        time.sleep(0.2)


def _write_lists(enabled, disabled, stopping):
    Gio, _ = _gio()
    shell = settings_for("org.gnome.shell")
    # Disable first so a replacement (Ubuntu dock -> JERONIX dock) never
    # shows two docks at once, then let the shell finish before enabling.
    shell.set_strv("disabled-extensions", disabled)
    Gio.Settings.sync()
    _wait_until_stopped(stopping)
    shell.set_strv("enabled-extensions", enabled)
    Gio.Settings.sync()


def write_extension_switches(layout):
    ext = layout.get("extensions", {})
    if not (ext.get("enable") or ext.get("disable")):
        return
    enabled, disabled = switched_lists(layout, *extension_lists())
    _write_lists(enabled, disabled, list(ext.get("disable", [])))


def apply(path, out=print):
    layout = load_layout(path)
    changes, skipped = resolve(layout)
    snap = take_snapshot(layout, changes)
    try:
        write_values(changes)
        write_extension_switches(layout)
    except Exception:
        restore(snap, out=lambda *_: None)
        raise
    ext = layout.get("extensions", {})
    out(f"applied layout {layout['name']} {layout['version']}: {len(changes)} settings, "
        f"{len(ext.get('enable', []))} extensions enabled, {len(ext.get('disable', []))} disabled")
    for name in skipped:
        out(f"  skipped (schema not installed): {name}")
    for rec in ext.get("recommended", []):
        out(f"  recommended extension (not enabled automatically): {rec['uuid']}")
    out(f"previous values saved to {snap}")
    out(f"undo with: scripts/jeronix_layout.py restore {snap}")
    return snap


def plan(path, out=print):
    d = describe(path)
    layout = d["layout"]
    out(f"layout {layout['name']} {layout['version']} would change:")
    for r in d["settings"]:
        out(f" {'*' if r['changed'] else ' '} {r['schema']} {r['key']}: {r['current']} -> {r['new']}")
    for r in d["extensions"]:
        out(f" {'*' if r['changed'] else ' '} extension {r['uuid']}: {r['action']}")
    for name in d["skipped"]:
        out(f"   skipped (schema not installed): {name}")
    return d


def load_snapshot(path):
    try:
        snap = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LayoutError(f"cannot read snapshot {path}: {e}") from e
    if not isinstance(snap, dict) or snap.get("schema") not in (1, SNAPSHOT_SCHEMA_VERSION) \
            or not isinstance(snap.get("entries"), list):
        raise LayoutError(f"{path} is not a JERONIX layout snapshot")
    for e in snap["entries"]:
        if not isinstance(e, dict) or set(e) != {"schema", "key", "user_value"}:
            raise LayoutError(f"{path}: malformed entry {e!r}")
        allowed = e["key"] in ALLOWED.get(e["schema"], ()) or \
            (e["schema"] == "org.gnome.shell" and e["key"] in EXTENSION_LIST_KEYS)
        if not allowed:
            raise LayoutError(f"{path}: entry {e!r} is not an allowed layout setting")
    return snap


def list_snapshots():
    directory = snapshot_dir()
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def _check_extension_restore(key, restored, current_value):
    """A restored extension list may only differ from the current one in
    SWITCHABLE extensions, so an edited snapshot cannot enable others."""
    changed = set(restored) ^ set(current_value)
    foreign = sorted(changed - SWITCHABLE)
    if foreign:
        raise LayoutError(f"snapshot would change {key} for non-JERONIX extensions {foreign}; refusing")


def restore(path=None, out=print):
    Gio, GLib = _gio()
    if path is None:
        snaps = list_snapshots()
        if not snaps:
            raise LayoutError(f"no snapshots in {snapshot_dir()}")
        path = snaps[-1]
    snap = load_snapshot(path)
    plan_ = []
    for e in snap["entries"]:
        found = schema_key(e["schema"], e["key"])
        if found is None:
            continue
        variant = None
        if e["user_value"] is not None:
            try:
                variant = GLib.Variant.parse(found[1].get_value_type(), e["user_value"], None, None)
            except GLib.Error as err:
                raise LayoutError(f"{e['schema']} {e['key']}: bad saved value: {err.message}") from err
        if e["schema"] == "org.gnome.shell" and e["key"] in EXTENSION_LIST_KEYS:
            settings = settings_for("org.gnome.shell")
            restored = variant.unpack() if variant is not None else \
                settings.get_default_value(e["key"]).unpack()
            _check_extension_restore(e["key"], restored, settings.get_strv(e["key"]))
        plan_.append((e, variant))
    lists = {}
    for e, variant in plan_:
        if e["schema"] == "org.gnome.shell" and e["key"] in EXTENSION_LIST_KEYS:
            lists[e["key"]] = variant
            continue
        settings = settings_for(e["schema"])
        if variant is None:
            settings.reset(e["key"])
        else:
            settings.set_value(e["key"], variant)
    Gio.Settings.sync()
    # Extension lists last, mirroring apply: disabled first, and the shell
    # must have stopped those extensions before enabled changes.
    if lists:
        shell = settings_for("org.gnome.shell")
        target = {}
        for key in EXTENSION_LIST_KEYS:
            if key in lists:
                v = lists[key]
                target[key] = v.unpack() if v is not None else shell.get_default_value(key).unpack()
            else:
                target[key] = shell.get_strv(key)
        stopping = sorted((set(shell.get_strv("enabled-extensions")) - set(target["enabled-extensions"]))
                          | (set(target["disabled-extensions"]) - set(shell.get_strv("disabled-extensions"))))
        _write_lists(target["enabled-extensions"], target["disabled-extensions"], stopping)
        # Keys that were at their default go back to "unset", not a copy.
        for key, v in lists.items():
            if v is None:
                shell.reset(key)
        Gio.Settings.sync()
    out(f"restored {len(plan_)} settings from {path}")
    return path


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
