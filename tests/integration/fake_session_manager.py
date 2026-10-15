#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal org.gnome.SessionManager stand-in for isolated test buses.

Implements Inhibit/Uninhibit/IsInhibited and exposes the currently held
cookies through org.jeronix.Test.FakeSessionManager.GetHeld so tests can
assert that an extension released everything it acquired. Never run this on
a real user session bus.
"""

import sys

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="org.gnome.SessionManager">
    <method name="Inhibit">
      <arg type="s" direction="in"/><arg type="u" direction="in"/>
      <arg type="s" direction="in"/><arg type="u" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="Uninhibit"><arg type="u" direction="in"/></method>
    <method name="IsInhibited">
      <arg type="u" direction="in"/><arg type="b" direction="out"/>
    </method>
  </interface>
  <interface name="org.jeronix.Test.FakeSessionManager">
    <method name="GetHeld">
      <arg type="a(usu)" direction="out"/>
    </method>
  </interface>
</node>
"""

held = {}  # cookie -> (app_id, flags)
next_cookie = 1


def on_method_call(conn, sender, path, iface, method, params, invocation):
    global next_cookie
    args = params.unpack()
    if method == "Inhibit":
        app_id, _xid, _reason, flags = args
        cookie = next_cookie
        next_cookie += 1
        held[cookie] = (app_id, flags)
        invocation.return_value(GLib.Variant("(u)", (cookie,)))
    elif method == "Uninhibit":
        if held.pop(args[0], None) is None:
            invocation.return_dbus_error("org.gnome.SessionManager.NotInhibited", "unknown cookie")
        else:
            invocation.return_value(None)
    elif method == "IsInhibited":
        hit = any(flags & args[0] for _app, flags in held.values())
        invocation.return_value(GLib.Variant("(b)", (hit,)))
    elif method == "GetHeld":
        rows = [(c, a, f) for c, (a, f) in sorted(held.items())]
        invocation.return_value(GLib.Variant("(a(usu))", (rows,)))
    else:
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)


def main():
    loop = GLib.MainLoop()
    node = Gio.DBusNodeInfo.new_for_xml(XML)

    def on_bus(conn, _name):
        for iface in node.interfaces:
            conn.register_object("/org/gnome/SessionManager", iface, on_method_call, None, None)

    def on_name(_conn, _name):
        print("READY", flush=True)

    def on_lost(_conn, _name):
        print("name lost", file=sys.stderr)
        loop.quit()

    Gio.bus_own_name(Gio.BusType.SESSION, "org.gnome.SessionManager",
                     Gio.BusNameOwnerFlags.NONE, on_bus, on_name, on_lost)
    loop.run()


if __name__ == "__main__":
    main()
