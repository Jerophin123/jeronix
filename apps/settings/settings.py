#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Settings: the whole system's settings in one window, laid out like
macOS System Settings. A searchable sidebar of colored categories, and each
category's page beside it.

Pages are built when first shown (pages.py); what exists is listed in
catalog.py. `settings.py --page wifi` opens a page directly (the Control
Center uses this); a second launch reuses the open window.
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from jeronix_common import style  # noqa: E402
from settings import catalog, pages  # noqa: E402

APP_ID = "io.jeronix.Settings"
ICONS = Path(__file__).resolve().parent / "icons"
TITLE = "JERONIX Settings"


def settings_css():
    """Sidebar icon squares and a few page details."""
    lines = [
        # Fixed 28 px squares (macOS System Settings), never stretched by the row.
        ".jeronix-sidebar-icon { border-radius: 7px; min-width: 28px; min-height: 28px; padding: 0; "
        "color: #FFFFFF; -gtk-icon-size: 16px; }",
        ".jeronix-account { padding: 6px 4px 10px 4px; }",
        ".jeronix-account-name { font-weight: 700; }",
        ".jeronix-style-preview { border-radius: 10px; }",
        ".jeronix-style-window { border-radius: 4px; }",
        ".jeronix-style-accent { border-radius: 2px; }",
        # The style cards' miniature desktops, in the JERONIX palettes.
        ".jeronix-style-light { background-color: #F2F5FA; }",
        ".jeronix-style-light .jeronix-style-window, .jeronix-style-light .jeronix-style-bar "
        "{ background-color: #FFFFFF; }",
        ".jeronix-style-light .jeronix-style-accent { background-color: #A65F30; }",
        ".jeronix-style-dark { background-color: #1C2230; }",
        ".jeronix-style-dark .jeronix-style-window, .jeronix-style-dark .jeronix-style-bar "
        "{ background-color: #2F3747; }",
        ".jeronix-style-dark .jeronix-style-accent { background-color: #D08A5C; }",
        ".jeronix-sidebar-search { margin: 6px 10px 4px 10px; }",
    ]
    lines += [f".jeronix-color-{name} {{ background-color: {color}; }}" for name, color in catalog.COLORS.items()]
    return "\n".join(lines) + "\n"


class SidebarRow(Gtk.ListBoxRow):
    """A sidebar entry: the page it opens and its group (-1: the account)."""

    def __init__(self, child, page_id, group, selectable=True):
        super().__init__(child=child, selectable=selectable)
        self.page_id = page_id
        self.group = group


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=TITLE, default_width=1000, default_height=700)
        self.set_size_request(360, 420)
        self._rows = {}
        self._built = set()
        self._matches = None

        # -- sidebar -------------------------------------------------------
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Search")
        self.search.add_css_class("jeronix-sidebar-search")
        self.search.connect("search-changed", self._on_search)
        self.search.connect("activate", self._on_search_activate)
        sidebar_box.append(self.search)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.append(self._account_row())
        for p in catalog.PAGES:
            row = self._page_row(p)
            self._rows[p.id] = row
            self.list.append(row)
        self.list.set_filter_func(self._filter)
        self.list.set_header_func(self._header)
        # Selecting a row (click or arrow keys) shows its page; activation
        # covers the account row, which is not selectable.
        self.list.connect("row-selected", self._on_row_activated)
        self.list.connect("row-activated", self._on_row_activated)
        scroller = Gtk.ScrolledWindow(child=self.list, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar_box.append(scroller)

        sidebar_view = Adw.ToolbarView(content=sidebar_box)
        sidebar_view.add_top_bar(Adw.HeaderBar(show_title=False))
        sidebar = Adw.NavigationPage(title="Settings", child=sidebar_view, tag="sidebar")

        # -- content -------------------------------------------------------
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.toasts = Adw.ToastOverlay(child=self.stack)
        content_view = Adw.ToolbarView(content=self.toasts)
        content_view.add_top_bar(Adw.HeaderBar())
        self.content = Adw.NavigationPage(title=TITLE, child=content_view, tag="content")

        self.split = Adw.NavigationSplitView(sidebar=sidebar, content=self.content,
                                             min_sidebar_width=240, max_sidebar_width=290)
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        narrow.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(narrow)
        self.set_content(self.split)

        shortcuts = Gtk.ShortcutController()
        shortcuts.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                                Gtk.CallbackAction.new(self._focus_search)))
        self.add_controller(shortcuts)

    # -- sidebar rows ------------------------------------------------------------

    def _account_row(self):
        name = GLib.get_real_name() or GLib.get_user_name()
        if name == "Unknown":
            name = GLib.get_user_name()
        box = Gtk.Box(spacing=10)
        box.add_css_class("jeronix-account")
        box.append(Adw.Avatar(size=40, text=name, show_initials=True))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("jeronix-account-name")
        text.append(title)
        subtitle = Gtk.Label(label=f"on {GLib.get_host_name()}", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")
        text.append(subtitle)
        box.append(text)
        return SidebarRow(box, "about", -1, selectable=False)

    def _page_row(self, p):
        box = Gtk.Box(spacing=10)
        icon = Gtk.Image(icon_name=p.icon, pixel_size=16, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        icon.add_css_class("jeronix-sidebar-icon")
        icon.add_css_class(f"jeronix-color-{p.color}")
        box.append(icon)
        box.append(Gtk.Label(label=p.title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        return SidebarRow(box, p.id, p.group)

    def _filter(self, row):
        if self._matches is None:
            return True
        return row.page_id in self._matches and row.group >= 0

    def _header(self, row, before):
        # Space between groups, as in macOS; none while searching.
        if before is not None and before.group != row.group and self._matches is None:
            row.set_header(Gtk.Box(height_request=10))
        else:
            row.set_header(None)

    def _on_search(self, entry):
        text = entry.get_text().strip()
        self._matches = None if not text else {p.id for p in catalog.search(text)}
        self.list.invalidate_filter()
        self.list.invalidate_headers()

    def _on_search_activate(self, entry):
        found = catalog.search(entry.get_text().strip())
        if found:
            self.show(found[0].id)

    def _focus_search(self, *_):
        self.search.grab_focus()
        return True

    def _on_row_activated(self, listbox, row):
        if row is not None:
            self.show(row.page_id)

    # -- pages ------------------------------------------------------------------

    def show(self, page_id):
        """Shows a page (building it the first time); unknown ids are ignored."""
        info = catalog.page(page_id)
        if info is None:
            return False
        if page_id not in self._built:
            self.stack.add_named(self._build(page_id), page_id)
            self._built.add(page_id)
        self.stack.set_visible_child_name(page_id)
        self.content.set_title(info.title)
        row = self._rows[page_id]
        if self.list.get_selected_row() is not row:
            self.list.select_row(row)
        self.split.set_show_content(True)
        return True

    def _build(self, page_id):
        # One page failing (an unexpected system) must not take the app down.
        try:
            return pages.BUILDERS[page_id](self)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            status = Adw.StatusPage(icon_name="dialog-warning-symbolic", title="This page could not be loaded",
                                    description=str(e))
            return status

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast.new(text))

    @property
    def window(self):
        return self


class SettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)
        # JERONIX's own symbolic icons for the sidebar and pages (apps/settings/icons).
        display = Gdk.Display.get_default()
        Gtk.IconTheme.get_for_display(display).add_search_path(str(ICONS))
        provider = Gtk.CssProvider()
        provider.load_from_string(settings_css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._settings_css = provider

    def do_command_line(self, command_line):
        window = self.get_active_window()
        first = window is None
        if first:
            window = SettingsWindow(self)
        wanted = catalog.page_argument(command_line.get_arguments()[1:])
        if not (wanted and window.show(wanted)) and first:
            window.show(catalog.DEFAULT_PAGE)
        window.present()
        return 0


def main(argv=None):
    return SettingsApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
