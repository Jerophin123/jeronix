#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A plain GTK 4 window used as a 'running application' in headless shell
tests. Usage: test_window.py TITLE [WIDTH HEIGHT]"""

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

TITLE = sys.argv[1] if len(sys.argv) > 1 else "JERONIX Test Window"
WIDTH, HEIGHT = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (640, 400)


def activate(app):
    win = Gtk.ApplicationWindow(application=app, title=TITLE, default_width=WIDTH, default_height=HEIGHT)
    label = Gtk.Label(label=TITLE)
    label.set_margin_top(40)
    win.set_child(label)
    win.present()


# Non-unique: every run opens its own window (two windows of one app).
app = Gtk.Application(application_id="io.jeronix.TestWindow", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.connect("activate", activate)
sys.exit(app.run([]))
