# SPDX-License-Identifier: GPL-3.0-or-later
"""GNOME Shell integration for JERONIX apps: extension state and switching
through the public org.gnome.Shell.Extensions D-Bus API, and GSettings for
settings schemas that ship inside an extension."""

from gi.repository import Gio, GLib

from . import paths

ACTIVE = 1


def _call(method, uuid):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return bus.call_sync("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", method,
                         GLib.Variant("(s)", (uuid,)), None, Gio.DBusCallFlags.NONE, 5000, None).unpack()


def extension_info(uuid):
    """The shell's info dict for uuid ({} if unknown or no shell)."""
    try:
        return _call("GetExtensionInfo", uuid)[0]
    except GLib.Error:
        return {}


def is_active(uuid):
    return int(extension_info(uuid).get("state", 0)) == ACTIVE


def set_enabled(uuid, enabled):
    """Enables or disables an installed extension; returns success."""
    try:
        return bool(_call("EnableExtension" if enabled else "DisableExtension", uuid)[0])
    except GLib.Error:
        return False


def extension_settings(uuid, schema_id):
    """Gio.Settings for a schema shipped in an installed extension, or None."""
    for directory in paths.extension_dirs(uuid):
        compiled = directory / "schemas" / "gschemas.compiled"
        if compiled.is_file():
            source = Gio.SettingsSchemaSource.new_from_directory(
                str(directory / "schemas"), Gio.SettingsSchemaSource.get_default(), False)
            schema = source.lookup(schema_id, False)
            if schema:
                return Gio.Settings.new_full(schema, None, None)
    return None


def open_gnome_settings(panel=None):
    """Opens GNOME Settings, optionally on a panel (e.g. 'display')."""
    argv = ["gnome-control-center"] + ([panel] if panel else [])
    Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
