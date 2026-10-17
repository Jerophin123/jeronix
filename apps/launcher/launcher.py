#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Launcher: search-first application launcher.

Type to search; Enter launches the best match; arrow keys move through
results; Esc closes. The sidebar browses Favorites (GNOME's dock
favorites), Recently Used and freedesktop categories. Opened from the
JERONIX menu, the dock's Applications button or Super+J.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from jeronix_common import paths, style  # noqa: E402
from launcher import catalog  # noqa: E402

APP_ID = "io.jeronix.Launcher"
ICON_SIZE = 64


class AppTile(Gtk.Box):
    def __init__(self, entry):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=124)
        self.entry = entry
        self.add_css_class("jeronix-tile")
        icon = Gtk.Image(pixel_size=ICON_SIZE)
        gicon = entry.info.get_icon() if entry.info else None
        if gicon:
            icon.set_from_gicon(gicon)
        else:
            icon.set_from_icon_name("application-x-executable")
        label = Gtk.Label(label=entry.name, wrap=True, max_width_chars=14, lines=2,
                          ellipsize=3, justify=Gtk.Justification.CENTER)
        self.append(icon)
        self.append(label)
        self.set_tooltip_text(entry.description or entry.name)
        self.update_property([Gtk.AccessibleProperty.LABEL], [entry.name])


class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="JERONIX Launcher", default_width=900, default_height=620)
        self._recent = catalog.RecentStore(paths.state_dir() / "launcher-recent.json")
        self._entries = catalog.load_entries(Gio.AppInfo.get_all())
        self._favorites = self._shell_favorites()
        self._category = "all"

        self.search = Gtk.SearchEntry(placeholder_text="Search applications", hexpand=True)
        self.search.add_css_class("jeronix-search")
        self.search.connect("search-changed", lambda *_: self._refresh())
        self.search.connect("activate", lambda *_: self._launch_first())
        self.search.connect("next-match", lambda *_: self._focus_results())
        self.search.set_key_capture_widget(self)

        header = Adw.HeaderBar()
        clamp = Adw.Clamp(maximum_size=560, child=self.search, hexpand=True)
        header.set_title_widget(clamp)

        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.add_css_class("navigation-sidebar")
        self.sidebar.connect("row-selected", self._on_category)
        sidebar_scroll = Gtk.ScrolledWindow(child=self.sidebar, width_request=220,
                                            hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar_scroll.add_css_class("jeronix-sidebar")

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True,
                                min_children_per_line=3, max_children_per_line=8,
                                row_spacing=6, column_spacing=6, valign=Gtk.Align.START,
                                activate_on_single_click=True)
        self.grid.set_margin_top(12)
        self.grid.set_margin_bottom(12)
        self.grid.set_margin_start(12)
        self.grid.set_margin_end(12)
        self.grid.connect("child-activated", lambda box, child: self._launch(child.get_child().entry))

        self.status = Adw.StatusPage(icon_name="system-search-symbolic", title="No applications found",
                                     description="Try a different word, or browse the categories.")
        self.stack = Gtk.Stack()
        self.stack.add_named(Gtk.ScrolledWindow(child=self.grid, hscrollbar_policy=Gtk.PolicyType.NEVER),
                             "results")
        self.stack.add_named(self.status, "empty")

        body = Gtk.Box()
        body.append(sidebar_scroll)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.stack.set_hexpand(True)
        body.append(self.stack)

        toolbar = Adw.ToolbarView(content=body)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self._fill_sidebar()
        self._refresh()
        self.search.grab_focus()

    @staticmethod
    def _shell_favorites():
        source = Gio.SettingsSchemaSource.get_default()
        if source and source.lookup("org.gnome.shell", True):
            return list(Gio.Settings.new("org.gnome.shell").get_strv("favorite-apps"))
        return []

    def _fill_sidebar(self):
        recent = self._recent.load()
        for cat_id, label, icon in catalog.categories_with_entries(self._entries, self._favorites, recent):
            row = Gtk.ListBoxRow()
            row.category = cat_id
            box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=label, xalign=0))
            row.set_child(box)
            self.sidebar.append(row)
        self.sidebar.select_row(self.sidebar.get_row_at_index(0))

    def _on_category(self, listbox, row):
        if row is None:
            return
        self._category = row.category
        if self.search.get_text():
            self.search.set_text("")  # browsing a category clears the search
        self._refresh()

    def visible_entries(self):
        recent = self._recent.load()
        query = self.search.get_text().strip()
        if query:
            return catalog.search(self._entries, query, recent)
        return catalog.in_category(self._entries, self._category, self._favorites, recent)

    def _refresh(self):
        self.grid.remove_all()
        entries = self.visible_entries()
        for entry in entries:
            self.grid.append(AppTile(entry))
        self.stack.set_visible_child_name("results" if entries else "empty")
        first = self.grid.get_child_at_index(0)
        if first:
            self.grid.select_child(first)

    def _focus_results(self):
        first = self.grid.get_child_at_index(0)
        if first:
            first.grab_focus()

    def _launch_first(self):
        selected = self.grid.get_selected_children()
        child = selected[0] if selected else self.grid.get_child_at_index(0)
        if child:
            self._launch(child.get_child().entry)

    def _launch(self, entry):
        context = Gdk.Display.get_default().get_app_launch_context()
        try:
            entry.info.launch([], context)
        except GLib.Error as e:
            dialog = Adw.AlertDialog(heading="Launch failed", body=f"Could not start {entry.name}: {e.message}")
            dialog.add_response("ok", "OK")
            dialog.present(self)
            return
        self._recent.add(entry.id)
        self.close()

    def _on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            if self.search.get_text():
                self.search.set_text("")
            else:
                self.close()
            return True
        if keyval == Gdk.KEY_Down and self.search.has_focus():
            self._focus_results()
            return True
        return False


class LauncherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)

    def do_activate(self):
        window = self.get_active_window() or LauncherWindow(self)
        window.present()


def main(argv=None):
    return LauncherApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
