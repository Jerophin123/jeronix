#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Settings: the JERONIX-specific controls (appearance, top bar,
dock, shortcuts) in one place, linking to GNOME Settings for everything the
system already manages (displays, sound, network, power, users)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from jeronix_common import shell, style  # noqa: E402

APP_ID = "io.jeronix.Settings"
THEME, PANEL, DOCK = "jeronix-shell-theme@jeronix", "jeronix-panel@jeronix", "jeronix-dock@jeronix"
SCHEMES = [("default", "Follow system"), ("prefer-light", "Light"), ("prefer-dark", "Dark")]
POSITIONS = [("bottom", "Bottom"), ("left", "Left"), ("right", "Right")]
BEHAVIORS = [("intellihide", "Hide when a window overlaps"), ("autohide", "Show at the screen edge"),
             ("always", "Always visible")]
SHORTCUTS = [
    ("Super", "Overview and search"),
    ("Super+J", "JERONIX Launcher"),
    ("Super+A", "All applications"),
    ("Ctrl+Alt+Tab", "Focus the top bar or the dock"),
    ("Super+Left / Right", "Tile a window"),
    ("Super+Page Up / Down", "Previous / next workspace"),
    ("Super+S", "Quick Settings"),
    ("Super+V", "Notifications and calendar"),
]
GNOME_PANELS = [("display", "Displays", "video-display-symbolic"),
                ("sound", "Sound", "audio-speakers-symbolic"),
                ("wifi", "Network and Wi-Fi", "network-wireless-symbolic"),
                ("bluetooth", "Bluetooth", "bluetooth-symbolic"),
                ("power", "Power", "battery-symbolic"),
                ("keyboard", "Keyboard and Shortcuts", "input-keyboard-symbolic"),
                ("users", "Users", "system-users-symbolic"),
                ("system", "About This System", "computer-symbolic")]


def combo_row(title, settings, key, choices):
    model = Gtk.StringList.new([label for _, label in choices])
    row = Adw.ComboRow(title=title, model=model)
    values = [value for value, _ in choices]

    def load(*_):
        current = settings.get_string(key)
        if current in values:
            row.set_selected(values.index(current))

    load()
    row.connect("notify::selected", lambda r, _: settings.set_string(key, values[r.get_selected()]))
    settings.connect(f"changed::{key}", load)
    return row


def extension_switch(title, subtitle, uuid):
    row = Adw.SwitchRow(title=title, subtitle=subtitle)
    installed = bool(shell.extension_info(uuid))
    row.set_sensitive(installed)
    if not installed:
        row.set_subtitle("Not installed")
    row.set_active(shell.is_active(uuid))
    row.connect("notify::active", lambda r, _: shell.set_enabled(uuid, r.get_active()))
    return row


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="JERONIX Settings", default_width=760, default_height=720)
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(self.appearance_page(), "appearance", "Appearance", "applications-graphics-symbolic")
        stack.add_titled_with_icon(self.panel_page(), "panel", "Top Bar", "view-continuous-symbolic")
        stack.add_titled_with_icon(self.dock_page(), "dock", "Dock", "user-bookmarks-symbolic")
        stack.add_titled_with_icon(self.shortcuts_page(), "shortcuts", "Shortcuts", "input-keyboard-symbolic")
        stack.add_titled_with_icon(self.system_page(), "system", "System", "emblem-system-symbolic")
        header = Adw.HeaderBar(title_widget=Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        toolbar = Adw.ToolbarView(content=stack)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

    def appearance_page(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Style")
        interface = Gio.Settings.new("org.gnome.desktop.interface")
        group.add(combo_row("Color scheme", interface, "color-scheme", SCHEMES))
        group.add(extension_switch("JERONIX shell theme", "Graphite, ivory and copper for the top bar, menus, "
                                   "Quick Settings and notifications", THEME))
        page.add(group)
        layouts = Adw.PreferencesGroup(title="Layout", description="Pure, Classic or Studio arrange the dock, "
                                       "top bar and workspaces differently.")
        studio = Adw.ButtonRow(title="Open Layout Studio", start_icon_name="view-dual-symbolic")
        studio.connect("activated", lambda *_: self.launch("io.jeronix.LayoutStudio.desktop"))
        layouts.add(studio)
        page.add(layouts)
        return page

    def panel_page(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Top bar")
        group.add(extension_switch("JERONIX top bar", "The JERONIX menu, workspaces and focused application", PANEL))
        settings = shell.extension_settings(PANEL, "org.gnome.shell.extensions.jeronix-panel")
        if settings:
            for key, title, subtitle in (
                    ("show-menu-label", "Show the JERONIX name", "Next to the menu symbol"),
                    ("show-workspaces", "Show workspaces", "Numbered buttons; click to switch, scroll to step"),
                    ("show-window-context", "Show the focused application", "With its window menu"),
                    ("hide-activities", "Replace Activities", "The JERONIX menu opens the overview instead")):
                row = Adw.SwitchRow(title=title, subtitle=subtitle)
                settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
                group.add(row)
            self._keep = getattr(self, "_keep", []) + [settings]
        page.add(group)
        return page

    def dock_page(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Dock")
        group.add(extension_switch("JERONIX dock", "Floating dock with favorites, running apps and previews", DOCK))
        settings = shell.extension_settings(DOCK, "org.gnome.shell.extensions.jeronix-dock")
        if settings:
            group.add(combo_row("Position", settings, "position", POSITIONS))
            group.add(combo_row("Visibility", settings, "behavior", BEHAVIORS))
            size = Adw.SpinRow.new_with_range(24, 72, 4)
            size.set_title("Icon size")
            size.set_subtitle("Icons shrink automatically when many apps are open")
            settings.bind("icon-size", size, "value", Gio.SettingsBindFlags.DEFAULT)
            group.add(size)
            for key, title in (("show-start-button", "Start button (opens the JERONIX Launcher)"),
                               ("show-search-button", "Search button (apps, files and settings)"),
                               ("magnify", "Magnify icons under the pointer"),
                               ("show-running", "Show running applications"),
                               ("show-previews", "Window previews on hover"),
                               ("show-apps-button", "Applications button at the end")):
                row = Adw.SwitchRow(title=title)
                settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
                group.add(row)
            self._keep = getattr(self, "_keep", []) + [settings]
        page.add(group)
        note = Adw.PreferencesGroup(description="Turning the JERONIX dock off does not turn Ubuntu's dock back on. "
                                    "Use Layout Studio → Restore to return to Ubuntu's dock.")
        page.add(note)
        return page

    def shortcuts_page(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Keyboard", description="JERONIX keeps every GNOME shortcut.")
        for keys, action in SHORTCUTS:
            row = Adw.ActionRow(title=action)
            label = Gtk.Label(label=keys, valign=Gtk.Align.CENTER)
            label.add_css_class("jeronix-key")
            row.add_suffix(label)
            group.add(row)
        page.add(group)
        more = Adw.PreferencesGroup()
        edit = Adw.ButtonRow(title="Change shortcuts in GNOME Settings", start_icon_name="input-keyboard-symbolic")
        edit.connect("activated", lambda *_: shell.open_gnome_settings("keyboard"))
        more.add(edit)
        page.add(more)
        return page

    def system_page(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="System settings", description="Hardware and accounts are managed by "
                                     "GNOME Settings, so they always work the same way.")
        for panel, title, icon in GNOME_PANELS:
            row = Adw.ActionRow(title=title, activatable=True)
            row.add_prefix(Gtk.Image(icon_name=icon))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda r, p=panel: shell.open_gnome_settings(p))
            group.add(row)
        page.add(group)
        info = Adw.PreferencesGroup()
        about = Adw.ButtonRow(title="JERONIX System Information", start_icon_name="help-about-symbolic")
        about.connect("activated", lambda *_: self.launch("io.jeronix.SystemInfo.desktop"))
        info.add(about)
        page.add(info)
        return page

    def launch(self, desktop_id):
        info = Gio.DesktopAppInfo.new(desktop_id)
        if info:
            info.launch([], None)


class SettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)

    def do_activate(self):
        (self.get_active_window() or SettingsWindow(self)).present()


def main(argv=None):
    return SettingsApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
