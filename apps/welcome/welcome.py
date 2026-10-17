#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Welcome: first-run tour with style and layout choices.

With --first-run (used by the autostart entry) it does nothing once the tour
has been completed or skipped, so it appears only once per user.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from jeronix_common import paths, previews, style  # noqa: E402

APP_ID = "io.jeronix.Welcome"
DONE_FLAG = "welcome-done"
STYLES = [("prefer-dark", "Dark", "Graphite surfaces, ivory text"),
          ("prefer-light", "Light", "Warm paper surfaces, graphite text"),
          ("default", "Follow system", "Switch with the system setting")]
ESSENTIALS = [("Super", "Overview: windows, workspaces and search"),
              ("Super+J", "JERONIX Launcher: type to find any app"),
              ("Ctrl+Alt+Tab", "Move keyboard focus to the top bar or dock"),
              ("Super+Left / Right", "Tile the window to half the screen")]


def done_flag():
    return paths.state_dir() / DONE_FLAG


def first_run_needed():
    return not done_flag().exists()


def mark_done():
    done_flag().write_text("1\n", encoding="utf-8")


def page(title, subtitle, child=None, eyebrow=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER,
                  margin_top=32, margin_bottom=32, margin_start=48, margin_end=48)
    if eyebrow:
        label = Gtk.Label(label=eyebrow.upper())
        label.add_css_class("jeronix-eyebrow")
        box.append(label)
    heading = Gtk.Label(label=title, wrap=True, justify=Gtk.Justification.CENTER)
    heading.add_css_class("title-1")
    box.append(heading)
    sub = Gtk.Label(label=subtitle, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=60)
    sub.add_css_class("jeronix-subtitle")
    box.append(sub)
    if child:
        box.append(child)
    return box


class WelcomeWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Welcome to JERONIX", default_width=900, default_height=640)
        self.tokens = style.load_tokens()
        self.tool = paths.layout_tool()
        self.style_manager = Adw.StyleManager.get_default()
        self.chosen_layout = None

        self.carousel = Adw.Carousel(allow_scroll_wheel=False, hexpand=True, vexpand=True)
        for p in (self.intro_page(), self.style_page(), self.layout_page(), self.essentials_page(), self.done_page()):
            self.carousel.append(p)
        dots = Adw.CarouselIndicatorDots(carousel=self.carousel)

        self.back = Gtk.Button(label="Back")
        self.back.connect("clicked", lambda *_: self.step(-1))
        self.next = Gtk.Button(label="Next")
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda *_: self.step(1))
        self.carousel.connect("page-changed", lambda *_: self.sync_buttons())

        header = Adw.HeaderBar(show_title=False)
        skip = Gtk.Button(label="Skip")
        skip.connect("clicked", lambda *_: self.finish())
        header.pack_end(skip)

        nav = Gtk.CenterBox(margin_start=24, margin_end=24, margin_bottom=20)
        nav.set_start_widget(self.back)
        nav.set_center_widget(dots)
        nav.set_end_widget(self.next)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.carousel)
        body.append(nav)
        self.toasts = Adw.ToastOverlay(child=body)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)
        self.sync_buttons()

    # -- pages -----------------------------------------------------------
    def intro_page(self):
        logo = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=140)
        lockup = paths.root() / "design" / "icons" / "jeronix-lockup-on-dark.svg"
        if not lockup.is_file():
            lockup = paths.root() / "branding" / "jeronix-lockup-on-dark.svg"
        if lockup.is_file():
            logo.set_filename(str(lockup))
        logo.set_size_request(-1, 96)
        return page("Welcome to JERONIX",
                    "A calm, handcrafted desktop built on Ubuntu's foundation: its kernel, drivers, "
                    "software and security updates, with a desktop shaped around your work.",
                    Adw.Clamp(maximum_size=360, child=logo), eyebrow="Hello")

    def style_page(self):
        interface = Gio.Settings.new("org.gnome.desktop.interface")
        group = Adw.PreferencesGroup()
        current = interface.get_string("color-scheme")
        first = None
        for value, title, subtitle in STYLES:
            check = Gtk.CheckButton(group=first, active=value == current)
            first = first or check
            check.connect("toggled", lambda c, v=value: c.get_active() and interface.set_string("color-scheme", v))
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable_widget=check)
            row.add_prefix(check)
            group.add(row)
        clamp = Adw.Clamp(maximum_size=460, child=group)
        return page("Light or dark?", "Change it any time in JERONIX Settings.", clamp, eyebrow="Style")

    def layout_page(self):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, max_children_per_line=3, min_children_per_line=3,
                           homogeneous=True, column_spacing=16, activate_on_single_click=True)
        self.layouts = self.tool.list_layouts(paths.layouts_dir())
        for path, layout in self.layouts:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class("jeronix-card")
            pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=130, can_shrink=True)
            pic.set_paintable(previews.preview_texture(layout, self.tokens, "dark"))
            title = Gtk.Label(label=layout["name"])
            title.add_css_class("title-4")
            summary = Gtk.Label(label=layout.get("summary", ""), wrap=True, max_width_chars=24,
                                justify=Gtk.Justification.CENTER)
            summary.add_css_class("jeronix-subtitle")
            for w in (pic, title, summary):
                card.append(w)
            card.layout_path = path
            flow.append(card)
        flow.connect("selected-children-changed",
                     lambda f: setattr(self, "chosen_layout",
                                       f.get_selected_children()[0].get_child().layout_path
                                       if f.get_selected_children() else None))
        return page("Choose a layout", "It is applied when you continue, and your current settings are saved "
                    "first. Try others later in Layout Studio.", flow, eyebrow="Layout")

    def essentials_page(self):
        group = Adw.PreferencesGroup()
        for keys, action in ESSENTIALS:
            row = Adw.ActionRow(title=action)
            label = Gtk.Label(label=keys, valign=Gtk.Align.CENTER)
            label.add_css_class("jeronix-key")
            row.add_suffix(label)
            group.add(row)
        return page("A few essentials", "Everything else works like GNOME.",
                    Adw.Clamp(maximum_size=520, child=group), eyebrow="Keyboard")

    def done_page(self):
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        for label, desktop_id in (("Layout Studio", "io.jeronix.LayoutStudio.desktop"),
                                  ("JERONIX Settings", "io.jeronix.Settings.desktop")):
            b = Gtk.Button(label=label)
            b.add_css_class("pill")
            b.connect("clicked", lambda *_, d=desktop_id: Gio.DesktopAppInfo.new(d) and
                      Gio.DesktopAppInfo.new(d).launch([], None))
            box.append(b)
        return page("You're all set", "Open the JERONIX menu in the top-left corner whenever you need these again.",
                    box, eyebrow="Done")

    # -- navigation ------------------------------------------------------
    def position(self):
        return round(self.carousel.get_position())

    def sync_buttons(self):
        pos, last = self.position(), self.carousel.get_n_pages() - 1
        self.back.set_sensitive(pos > 0)
        self.next.set_label("Start using JERONIX" if pos == last else "Next")

    def step(self, delta):
        pos = self.position()
        if delta > 0 and pos == 2 and self.chosen_layout:
            if not self.apply_layout():
                return
        if delta > 0 and pos == self.carousel.get_n_pages() - 1:
            self.finish()
            return
        target = max(0, min(self.carousel.get_n_pages() - 1, pos + delta))
        self.carousel.scroll_to(self.carousel.get_nth_page(target), True)

    def apply_layout(self):
        try:
            self.tool.apply(self.chosen_layout, out=lambda *_: None)
        except self.tool.LayoutError as e:
            dialog = Adw.AlertDialog(heading="This layout cannot be applied", body=str(e))
            dialog.add_response("ok", "OK")
            dialog.present(self)
            return False
        self.toasts.add_toast(Adw.Toast(title="Layout applied. Undo it any time in Layout Studio → Restore."))
        self.chosen_layout = None
        return True

    def finish(self):
        mark_done()
        self.close()


class WelcomeApp(Adw.Application):
    def __init__(self, first_run=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.first_run = first_run

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)

    def do_activate(self):
        (self.get_active_window() or WelcomeWindow(self)).present()


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    first_run = "--first-run" in argv
    if first_run and not first_run_needed():
        return 0
    return WelcomeApp(first_run).run([a for a in argv if a != "--first-run"])


if __name__ == "__main__":
    sys.exit(main())
