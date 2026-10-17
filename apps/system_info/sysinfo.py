#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX System Information: branded OS, hardware and desktop details,
with a plain-text report for support requests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from jeronix_common import paths, style  # noqa: E402
from system_info import collect  # noqa: E402

APP_ID = "io.jeronix.SystemInfo"


def branding_file(name):
    for candidate in (paths.root() / "design" / "icons" / name, paths.root() / "branding" / name):
        if candidate.is_file():
            return candidate
    return None


class InfoWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="JERONIX System Information", default_width=640, default_height=760)
        self.style_manager = Adw.StyleManager.get_default()
        self.info = collect.collect()
        self.extensions = collect.extension_states()
        self.toolkit = {
            "GTK": f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
            "libadwaita": f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}",
        }
        self.toasts = Adw.ToastOverlay()

        page = Adw.PreferencesPage()
        hero = Adw.PreferencesGroup()
        self.logo = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=110, margin_top=12)
        self._sync_logo()
        self.style_manager.connect("notify::dark", lambda *_: self._sync_logo())
        hero.add(self.logo)
        tagline = Gtk.Label(label="A handcrafted desktop on the Ubuntu foundation", margin_bottom=12)
        tagline.add_css_class("jeronix-subtitle")
        hero.add(tagline)
        page.add(hero)

        system = Adw.PreferencesGroup(title="System")
        for key in ("JERONIX", "Base system", "Kernel", "Architecture", "GNOME Shell", "Session"):
            system.add(self._row(key, self.info[key]))
        for key, value in self.toolkit.items():
            system.add(self._row(key, value))
        page.add(system)

        hardware = Adw.PreferencesGroup(title="Hardware")
        for key in ("Processor", "Memory", "Disk (/)", "Graphics driver", "Virtualization"):
            hardware.add(self._row(key, self.info[key]))
        page.add(hardware)

        desktop = Adw.PreferencesGroup(title="JERONIX desktop components")
        names = {"jeronix-shell-theme@jeronix": "Shell theme", "jeronix-panel@jeronix": "Top bar",
                 "jeronix-dock@jeronix": "Dock", "jeronix-quick-settings@jeronix": "Stay Awake"}
        for uuid, state in self.extensions.items():
            row = self._row(names.get(uuid, uuid), state)
            icon = "emblem-ok-symbolic" if state == "active" else "dialog-information-symbolic"
            row.add_prefix(Gtk.Image(icon_name=icon))
            desktop.add(row)
        page.add(desktop)

        support = Adw.PreferencesGroup(title="Support")
        copy = Adw.ButtonRow(title="Copy System Report", start_icon_name="edit-copy-symbolic")
        copy.connect("activated", lambda *_: self.copy_report())
        support.add(copy)
        settings = Adw.ButtonRow(title="Open GNOME Settings → About", start_icon_name="emblem-system-symbolic")
        settings.connect("activated", lambda *_: Gio.Subprocess.new(["gnome-control-center", "system"],
                                                                     Gio.SubprocessFlags.NONE))
        support.add(settings)
        page.add(support)

        self.toasts.set_child(page)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_content(toolbar)

    def _sync_logo(self):
        name = "jeronix-lockup-on-dark.svg" if self.style_manager.get_dark() else "jeronix-lockup-on-light.svg"
        path = branding_file(name)
        if path:
            self.logo.set_filename(str(path))

    @staticmethod
    def _row(title, value):
        row = Adw.ActionRow(title=title, subtitle=str(value), subtitle_selectable=True)
        row.add_css_class("property")
        return row

    def report(self):
        return collect.report(self.info, self.extensions, self.toolkit)

    def copy_report(self):
        Gdk.Display.get_default().get_clipboard().set(self.report())
        self.toasts.add_toast(Adw.Toast(title="System report copied to the clipboard"))


class InfoApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)

    def do_activate(self):
        (self.get_active_window() or InfoWindow(self)).present()


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    if "--report" in argv:  # plain-text report on stdout, no window
        print(collect.report(collect.collect(), collect.extension_states(), {}), end="")
        return 0
    return InfoApp().run(argv)


if __name__ == "__main__":
    sys.exit(main())
