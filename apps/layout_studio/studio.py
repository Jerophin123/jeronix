#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Layout Studio: preview, apply and restore desktop layouts.

A front end for scripts/jeronix_layout.py: every layout is validated against
this system, the exact changes are listed before applying, a snapshot is
saved first, and any snapshot can be restored.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi  # noqa: E402

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from jeronix_common import paths, previews, style  # noqa: E402

APP_ID = "io.jeronix.LayoutStudio"

LABELS = {
    "color-scheme": "Style", "accent-color": "System accent", "enable-hot-corners": "Hot corner",
    "clock-show-weekday": "Weekday in clock", "button-layout": "Title bar buttons",
    "action-double-click-titlebar": "Double-click title bar", "overlay-key": "Overview key",
    "dynamic-workspaces": "Dynamic workspaces", "workspaces-only-on-primary": "Workspaces on primary only",
    "edge-tiling": "Edge tiling", "center-new-windows": "Center new windows", "num-workspaces": "Workspaces",
    "picture-uri": "Wallpaper", "picture-uri-dark": "Dark wallpaper", "picture-options": "Wallpaper fit",
    "primary-color": "Background color", "current-workspace-only": "Alt+Tab: current workspace only",
    "show-menu-label": "Top bar: JERONIX label", "show-workspaces": "Top bar: workspaces",
    "show-window-context": "Top bar: focused app", "hide-activities": "Top bar: replace Activities",
    "position": "Dock position", "behavior": "Dock behavior", "icon-size": "Dock icon size",
    "show-running": "Dock: running apps", "show-previews": "Dock: window previews",
}
EXTENSION_NAMES = {
    "jeronix-shell-theme@jeronix": "JERONIX shell theme", "jeronix-panel@jeronix": "JERONIX top bar",
    "jeronix-dock@jeronix": "JERONIX dock", "jeronix-quick-settings@jeronix": "Stay Awake",
    "ubuntu-dock@ubuntu.com": "Ubuntu Dock", "ding@rastersoft.com": "Desktop icons",
}


def label_for(row):
    name = LABELS.get(row["key"], row["key"])
    if row["schema"].endswith("wm.keybindings") or row["schema"].endswith("shell.keybindings"):
        name = f"Shortcut: {row['key'].replace('-', ' ')}"
    return name


def short(value):
    value = value.strip("'")
    if value.startswith("file://"):
        return Path(value).name
    return value if len(value) <= 40 else value[:37] + "…"


class LayoutCard(Gtk.Box):
    def __init__(self, path, layout, tokens, dark):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.path, self.layout = path, layout
        self.add_css_class("jeronix-card")
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True,
                                   width_request=240, height_request=150)
        self.set_preview(tokens, dark)
        title = Gtk.Label(label=layout["name"], xalign=0)
        title.add_css_class("title-3")
        summary = Gtk.Label(label=layout.get("summary", ""), xalign=0, wrap=True, max_width_chars=30)
        summary.add_css_class("jeronix-subtitle")
        self.append(self.picture)
        self.append(title)
        self.append(summary)
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"{layout['name']} layout"])

    def set_preview(self, tokens, dark):
        self.picture.set_paintable(previews.preview_texture(self.layout, tokens, "dark" if dark else "light"))


class StudioWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="JERONIX Layout Studio", default_width=1100, default_height=740)
        self.tool = paths.layout_tool()
        self.tokens = style.load_tokens()
        self.style_manager = Adw.StyleManager.get_default()
        self.toasts = Adw.ToastOverlay()

        header = Adw.HeaderBar()
        restore = Gtk.Button(label="Restore…", tooltip_text="Go back to the settings saved before a layout was applied")
        restore.connect("clicked", lambda *_: self.show_restore_dialog())
        header.pack_start(restore)

        self.cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, max_children_per_line=1,
                                 row_spacing=12, valign=Gtk.Align.START, activate_on_single_click=True)
        for m in ("top", "bottom", "start", "end"):
            getattr(self.cards, f"set_margin_{m}")(16)
        self.cards.connect("selected-children-changed", lambda *_: self.show_selected())
        self.card_list = []
        for path, layout in self.tool.list_layouts(paths.layouts_dir()):
            card = LayoutCard(path, layout, self.tokens, self.style_manager.get_dark())
            self.cards.append(card)
            self.card_list.append(card)
        self.style_manager.connect("notify::dark", lambda *_: [c.set_preview(self.tokens, self.style_manager.get_dark())
                                                               for c in self.card_list])
        left = Gtk.ScrolledWindow(child=self.cards, width_request=320, hscrollbar_policy=Gtk.PolicyType.NEVER)

        self.details = Adw.PreferencesPage()
        body = Gtk.Box()
        body.append(left)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.details.set_hexpand(True)
        body.append(self.details)

        self.toasts.set_child(body)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)
        if self.card_list:
            self.cards.select_child(self.cards.get_child_at_index(0))

    # -- details ---------------------------------------------------------
    def selected(self):
        sel = self.cards.get_selected_children()
        return sel[0].get_child() if sel else None

    def show_selected(self):
        card = self.selected()
        if card is None:
            return
        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup(title=card.layout["name"], description=card.layout["description"])
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=260)
        picture.set_paintable(previews.preview_texture(card.layout, self.tokens,
                                                       "dark" if self.style_manager.get_dark() else "light"))
        intro.add(picture)
        apply = Gtk.Button(label=f"Apply {card.layout['name']}", halign=Gtk.Align.CENTER, margin_top=12)
        apply.add_css_class("suggested-action")
        apply.add_css_class("pill")
        apply.connect("clicked", lambda *_: self.confirm_apply(card))
        intro.add(apply)
        page.add(intro)
        try:
            plan = self.tool.describe(card.path)
        except self.tool.LayoutError as e:
            apply.set_sensitive(False)
            problem = Adw.PreferencesGroup(title="This layout cannot be applied here")
            problem.add(Adw.ActionRow(title="Reason", subtitle=str(e), subtitle_selectable=True))
            page.add(problem)
            self._swap_details(page)
            return
        self.current_plan = plan
        changed = [r for r in plan["settings"] if r["changed"]]
        group = Adw.PreferencesGroup(
            title="What changes",
            description=f"{len(changed)} of {len(plan['settings'])} settings differ from yours. "
                        "Your current values are saved before anything changes.")
        for r in plan["settings"]:
            row = Adw.ActionRow(title=label_for(r),
                                subtitle=f"{short(r['current'])} → {short(r['new'])}" if r["changed"]
                                else f"already {short(r['new'])}")
            if r["changed"]:
                row.add_prefix(Gtk.Image(icon_name="emblem-synchronizing-symbolic"))
            group.add(row)
        page.add(group)
        if plan["extensions"]:
            ext_group = Adw.PreferencesGroup(title="Shell components")
            for r in plan["extensions"]:
                verb = "Turn on" if r["action"] == "enable" else "Turn off"
                row = Adw.ActionRow(title=EXTENSION_NAMES.get(r["uuid"], r["uuid"]),
                                    subtitle=f"{verb}" + ("" if r["changed"] else " (already)"))
                ext_group.add(row)
            page.add(ext_group)
        if card.layout.get("limitations"):
            lim = Adw.PreferencesGroup(title="Good to know")
            for text in card.layout["limitations"]:
                lim.add(Adw.ActionRow(title=text, title_lines=0))
            page.add(lim)
        self._swap_details(page)

    def _swap_details(self, page):
        parent = self.details.get_parent()
        parent.remove(self.details)
        page.set_hexpand(True)
        parent.append(page)
        self.details = page

    # -- actions ---------------------------------------------------------
    def confirm_apply(self, card):
        changes = sum(r["changed"] for r in self.current_plan["settings"]) + \
            sum(r["changed"] for r in self.current_plan["extensions"])
        dialog = Adw.AlertDialog(
            heading=f"Apply {card.layout['name']}?",
            body=f"{changes} changes take effect immediately. Your current settings are saved first, "
                 "so you can restore them at any time.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("apply", "Apply")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda d, r: r == "apply" and self.apply(card))
        dialog.present(self)

    def apply(self, card):
        try:
            snapshot = self.tool.apply(card.path, out=lambda *_: None)
        except self.tool.LayoutError as e:
            self.error("Could not apply the layout", str(e))
            return
        toast = Adw.Toast(title=f"{card.layout['name']} applied", button_label="Undo", timeout=10)
        toast.connect("button-clicked", lambda *_: self.restore(snapshot))
        self.toasts.add_toast(toast)
        self.show_selected()

    def restore(self, snapshot):
        try:
            self.tool.restore(snapshot, out=lambda *_: None)
        except self.tool.LayoutError as e:
            self.error("Could not restore", str(e))
            return
        self.toasts.add_toast(Adw.Toast(title="Previous settings restored"))
        self.show_selected()

    def show_restore_dialog(self):
        snaps = list(reversed(self.tool.list_snapshots()))
        dialog = Adw.Dialog(title="Restore settings", content_width=520, content_height=440)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            description="Each time a layout is applied, the settings it changes are saved first. "
                        "Restoring puts them back exactly.")
        if not snaps:
            group.add(Adw.ActionRow(title="No saved settings yet"))
        for snap in snaps:
            name, when = snap.stem.split("-", 1)[-1], snap.stem.split("-", 1)[0]
            try:
                stamp = datetime.strptime(when, "%Y%m%dT%H%M%S%fZ").strftime("%Y-%m-%d %H:%M:%S UTC")
            except ValueError:
                stamp = when
            row = Adw.ActionRow(title=f"Before applying {name.title()}", subtitle=stamp)
            button = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
            button.connect("clicked", lambda b, s=snap: (dialog.close(), self.restore(s)))
            row.add_suffix(button)
            group.add(row)
        page.add(group)
        toolbar = Adw.ToolbarView(content=page)
        toolbar.add_top_bar(Adw.HeaderBar())
        dialog.set_child(toolbar)
        dialog.present(self)

    def error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)


class StudioApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        style.apply(self)

    def do_activate(self):
        (self.get_active_window() or StudioWindow(self)).present()


def main(argv=None):
    return StudioApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
