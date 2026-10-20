#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Layout Studio: preview, apply and restore desktop layouts.

A front end for scripts/jeronix_layout.py: every layout is validated against
this system, the exact changes are listed before applying, a snapshot is
saved first, and any snapshot can be restored.

The window shows the layouts side by side, each as a picture of the desktop
it makes (previews.py) and marked "In use" when it is the shape of the
desktop now. The one selected is shown below: its picture, what it is, and
what applying it changes, in plain words and grouped by where it shows.
"""

import ast
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
DOCK = "org.gnome.shell.extensions.jeronix-dock"
PANEL = "org.gnome.shell.extensions.jeronix-panel"

# Where each setting shows, in this order: (section, its description).
SECTIONS = {
    "taskbar": ("Taskbar", "Start, your apps, the tray and the widgets"),
    "top-bar": ("Top bar", "GNOME's bar at the top of the screen, where the layout keeps it"),
    "windows": ("Windows", "Title bars and how windows open and tile"),
    "workspaces": ("Workspaces and keyboard", "Workspaces, the Super key and shortcuts"),
    "look": ("Look", "Style, colors, wallpaper, icons and fonts"),
}

# key -> (label, section). Keys of other schemas than the JERONIX ones are
# GNOME's; shortcuts are named from their key.
LABELS = {
    # taskbar (jeronix-dock)
    "style": ("Bar", "taskbar"), "position": ("Screen edge", "taskbar"), "alignment": ("Apps", "taskbar"),
    "behavior": ("Visibility", "taskbar"), "icon-size": ("Icon size", "taskbar"),
    "system-tray": ("Tray and clock in the bar", "taskbar"), "hide-top-bar": ("Hide GNOME's top bar", "taskbar"),
    "show-start-button": ("Start button", "taskbar"), "show-search-button": ("Search button", "taskbar"),
    "show-task-view-button": ("Task View button", "taskbar"), "show-apps-button": ("All apps button", "taskbar"),
    "show-running": ("Running apps", "taskbar"), "show-previews": ("Window previews", "taskbar"),
    "magnify": ("Magnify icons", "taskbar"), "live-updates": ("Live updates and widgets", "taskbar"),
    "super-key-start-menu": ("Super key opens Start", "workspaces"),
    "hide-overview-dash": ("Task View without the app dash", "workspaces"),
    # top bar (jeronix-panel)
    "show-menu-label": ("JERONIX label", "top-bar"), "show-workspaces": ("Workspaces", "top-bar"),
    "show-window-context": ("Focused app", "top-bar"), "hide-activities": ("Replace Activities", "top-bar"),
    # windows
    "button-layout": ("Title bar buttons", "windows"), "action-double-click-titlebar": ("Double-click title bar", "windows"),
    "edge-tiling": ("Edge tiling", "windows"), "center-new-windows": ("New windows centered", "windows"),
    "focus-mode": ("Focus", "windows"),
    # workspaces and keyboard
    "overlay-key": ("Super key", "workspaces"), "enable-hot-corners": ("Hot corner", "workspaces"),
    "dynamic-workspaces": ("Workspaces come and go", "workspaces"), "num-workspaces": ("Workspaces", "workspaces"),
    "workspaces-only-on-primary": ("Workspaces on the main screen only", "workspaces"),
    "current-workspace-only": ("Alt+Tab: this workspace only", "workspaces"),
    # look
    "color-scheme": ("Style", "look"), "accent-color": ("Accent color", "look"), "icon-theme": ("Icons", "look"),
    "gtk-theme": ("Older apps' theme", "look"), "cursor-theme": ("Pointer", "look"), "font-name": ("Interface font", "look"),
    "document-font-name": ("Document font", "look"), "monospace-font-name": ("Monospace font", "look"),
    "theme-name": ("Sounds", "look"), "clock-show-weekday": ("Weekday in the clock", "look"),
    "clock-show-seconds": ("Seconds in the clock", "look"), "clock-format": ("Clock", "look"),
    "show-battery-percentage": ("Battery percentage", "look"), "enable-animations": ("Animations", "look"),
    "picture-uri": ("Wallpaper", "look"), "picture-uri-dark": ("Dark wallpaper", "look"),
    "picture-options": ("Wallpaper fit", "look"), "primary-color": ("Background color", "look"),
}

# Values in words, by key.
VALUES = {
    "style": {"modules": "Floating modules", "taskbar": "Full-width taskbar", "floating": "Floating dock"},
    "position": {"bottom": "Bottom", "left": "Left edge", "right": "Right edge"},
    "alignment": {"center": "Centered", "start": "At the start"},
    "behavior": {"always": "Always visible", "intellihide": "Steps aside under windows",
                 "autohide": "Hidden until you reach the edge"},
    "color-scheme": {"prefer-dark": "Dark", "prefer-light": "Light", "default": "Default"},
    "action-double-click-titlebar": {"toggle-maximize": "Maximize", "minimize": "Minimize", "none": "Nothing",
                                     "toggle-shade": "Shade", "lower": "Lower", "menu": "Menu"},
    "picture-options": {"zoom": "Fill", "scaled": "Fit", "centered": "Center", "stretched": "Stretch",
                        "spanned": "Span", "wallpaper": "Tile", "none": "None"},
    "focus-mode": {"click": "On click", "sloppy": "On hover", "mouse": "Follows the pointer"},
    "clock-format": {"24h": "24-hour", "12h": "12-hour"},
}
EXTENSION_NAMES = {
    "jeronix-shell-theme@jeronix": "JERONIX shell theme",
    "jeronix-panel@jeronix": "JERONIX top bar and menu",
    "jeronix-dock@jeronix": "JERONIX taskbar, Start and widgets",
    "jeronix-quick-settings@jeronix": "JERONIX Quick Settings",
    "ubuntu-dock@ubuntu.com": "Ubuntu Dock",
    "ding@rastersoft.com": "Desktop icons",
}
# What makes a layout's shape: when these match, it is the layout in use.
IDENTITY = ("style", "position", "alignment")


def label_for(row):
    """(label, section) of a planned setting."""
    if row["schema"].endswith("wm.keybindings") or row["schema"].endswith("shell.keybindings"):
        return f"Shortcut: {row['key'].replace('-', ' ')}", "workspaces"
    return LABELS.get(row["key"], (row["key"].replace("-", " ").capitalize(), "look"))


def _parse(text):
    """A GVariant's printed text as a Python value (text itself if not)."""
    text = text.strip()
    if text.startswith("@"):  # a type annotation: "@as []"
        text = text.split(" ", 1)[-1]
    try:
        return ast.literal_eval(text.replace("true", "True").replace("false", "False"))
    except (ValueError, SyntaxError):
        return text


def _shortcut(accel):
    return accel.replace("<Super>", "Super+").replace("<Shift>", "Shift+").replace("<Control>", "Ctrl+") \
        .replace("<Alt>", "Alt+").replace("<Primary>", "Ctrl+")


def human(key, text):
    """A setting's value in words."""
    value = _parse(text)
    if isinstance(value, bool):
        return "On" if value else "Off"
    if isinstance(value, list):
        return ", ".join(_shortcut(v) for v in value) if value else "None"
    if isinstance(value, int):
        return f"{value} px" if key == "icon-size" else str(value)
    value = str(value)
    if key in VALUES:
        return VALUES[key].get(value, value)
    if key == "button-layout":
        buttons = [b for b in value.split(":")[-1].split(",") if b]
        return ", ".join(buttons).capitalize() if buttons else "None"
    if value.startswith("file://"):
        return Path(value).name
    return value if len(value) <= 40 else value[:37] + "…"


def in_use(plan):
    """Whether a layout is the shape of the desktop now (its bar's style,
    edge and alignment, and its components switched as it wants)."""
    rows = {r["key"]: r for r in plan["settings"] if r["schema"] == DOCK}
    style_row = rows.get("style")
    floating = style_row is not None and _parse(style_row["new"]) == "floating"
    keys = [k for k in IDENTITY if k in rows and not (k == "alignment" and floating)]
    components = [r for r in plan["extensions"] if r["uuid"] == "jeronix-dock@jeronix"]
    return bool(keys) and all(not rows[k]["changed"] for k in keys) and all(not r["changed"] for r in components)


class LayoutCard(Gtk.Box):
    """A layout in the gallery: its picture, name, "In use" and summary."""

    def __init__(self, path, layout, tokens, dark):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.path, self.layout = path, layout
        self.add_css_class("jeronix-card")
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, height_request=150)
        self.set_preview(tokens, dark)
        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label=layout["name"], xalign=0, hexpand=True)
        title.add_css_class("title-3")
        self.badge = Gtk.Label(label="In use", visible=False, valign=Gtk.Align.CENTER)
        self.badge.add_css_class("jeronix-badge")
        head.append(title)
        head.append(self.badge)
        summary = Gtk.Label(label=layout.get("summary", ""), xalign=0, wrap=True, max_width_chars=24,
                            valign=Gtk.Align.START, vexpand=True)
        summary.add_css_class("jeronix-subtitle")
        self.append(self.picture)
        self.append(head)
        self.append(summary)
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"{layout['name']} layout"])

    def set_preview(self, tokens, dark):
        self.picture.set_paintable(previews.preview_texture(self.layout, tokens, "dark" if dark else "light"))

    def set_in_use(self, used):
        self.badge.set_visible(used)
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [f"{self.layout['name']} layout" + (", in use" if used else "")])


class StudioWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="JERONIX Layout Studio", default_width=1100, default_height=780)
        self.tool = paths.layout_tool()
        self.tokens = style.load_tokens()
        self.style_manager = Adw.StyleManager.get_default()
        self.toasts = Adw.ToastOverlay()
        self.current_plan = None

        header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Layout Studio",
                                                             subtitle="How your desktop is arranged"))
        restore = Gtk.Button(child=Adw.ButtonContent(icon_name="edit-undo-symbolic", label="Restore…"),
                             tooltip_text="Go back to the settings saved before a layout was applied")
        restore.connect("clicked", lambda *_: self.show_restore_dialog())
        header.pack_start(restore)

        # The gallery: every layout side by side.
        self.cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, max_children_per_line=3,
                                 min_children_per_line=3, homogeneous=True, column_spacing=12, row_spacing=12,
                                 valign=Gtk.Align.START, activate_on_single_click=True)
        self.cards.connect("selected-children-changed", lambda *_: self.show_selected())
        self.card_list = []
        for path, layout in self.tool.list_layouts(paths.layouts_dir()):
            card = LayoutCard(path, layout, self.tokens, self.style_manager.get_dark())
            self.cards.append(card)
            self.card_list.append(card)
        self.style_manager.connect("notify::dark", lambda *_: self.restyle())

        gallery_title = Gtk.Label(label="Layouts", xalign=0)
        gallery_title.add_css_class("title-4")
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=24,
                         margin_start=18, margin_end=18)
        column.append(gallery_title)
        column.append(self.cards)
        column.append(self.details)
        scroller = Gtk.ScrolledWindow(child=Adw.Clamp(child=column, maximum_size=1040),
                                      hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.toasts.set_child(scroller)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

        self.refresh_in_use()
        if self.card_list:
            used = next((c for c in self.card_list if c.badge.get_visible()), self.card_list[0])
            self.cards.select_child(used.get_parent())

    def restyle(self):
        for card in self.card_list:
            card.set_preview(self.tokens, self.style_manager.get_dark())
        self.show_selected()

    def refresh_in_use(self):
        for card in self.card_list:
            try:
                card.set_in_use(in_use(self.tool.describe(card.path)))
            except self.tool.LayoutError:
                card.set_in_use(False)

    # -- details ---------------------------------------------------------
    def selected(self):
        sel = self.cards.get_selected_children()
        return sel[0].get_child() if sel else None

    def show_selected(self):
        card = self.selected()
        if card is None:
            return
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=12)
        page.append(self.hero(card))
        try:
            plan = self.tool.describe(card.path)
        except self.tool.LayoutError as e:
            self.apply_button.set_sensitive(False)
            problem = Adw.PreferencesGroup(title="This layout cannot be applied here")
            problem.add(Adw.ActionRow(title="Reason", subtitle=str(e), subtitle_selectable=True))
            page.append(problem)
            self._swap_details(page)
            return
        self.current_plan = plan
        changes = sum(r["changed"] for r in plan["settings"]) + sum(r["changed"] for r in plan["extensions"])
        self.apply_button.set_sensitive(changes > 0)
        self.apply_button.set_label(f"Apply {card.layout['name']}" if changes else "Nothing to change")
        self.hero_note.set_label(
            f"{changes} change{'s' if changes != 1 else ''}. Your current settings are saved first, "
            "so you can go back at any time." if changes else "Your desktop already matches this layout.")
        for group in self.change_groups(plan):
            page.append(group)
        if plan["extensions"]:
            ext_group = Adw.PreferencesGroup(title="Shell components")
            for r in plan["extensions"]:
                verb = "Turned on" if r["action"] == "enable" else "Turned off"
                row = Adw.ActionRow(title=EXTENSION_NAMES.get(r["uuid"], r["uuid"]),
                                    subtitle=verb if r["changed"] else f"Already {verb.lower()[7:]}")
                if r["changed"]:
                    row.add_prefix(Gtk.Image(icon_name="emblem-synchronizing-symbolic"))
                ext_group.add(row)
            page.append(ext_group)
        if card.layout.get("limitations"):
            lim = Adw.PreferencesGroup(title="Good to know")
            for text in card.layout["limitations"]:
                lim.add(Adw.ActionRow(title=text, title_lines=0))
            page.append(lim)
        self._swap_details(page)

    def hero(self, card):
        """The selected layout: a large picture, what it is, and Apply."""
        hero = Gtk.Box(spacing=24)
        hero.add_css_class("jeronix-card")
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, width_request=420,
                              height_request=262, valign=Gtk.Align.CENTER)
        picture.set_paintable(previews.preview_texture(card.layout, self.tokens,
                                                       "dark" if self.style_manager.get_dark() else "light"))
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER, hexpand=True)
        eyebrow = Gtk.Label(label="IN USE" if card.badge.get_visible() else "LAYOUT", xalign=0)
        eyebrow.add_css_class("jeronix-eyebrow")
        name = Gtk.Label(label=card.layout["name"], xalign=0)
        name.add_css_class("title-1")
        description = Gtk.Label(label=card.layout.get("description", ""), xalign=0, wrap=True)
        self.apply_button = Gtk.Button(label=f"Apply {card.layout['name']}", halign=Gtk.Align.START, margin_top=8)
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.add_css_class("pill")
        self.apply_button.connect("clicked", lambda *_: self.confirm_apply(card))
        self.hero_note = Gtk.Label(xalign=0, wrap=True)
        self.hero_note.add_css_class("jeronix-subtitle")
        for widget in (eyebrow, name, description, self.apply_button, self.hero_note):
            text.append(widget)
        hero.append(picture)
        hero.append(text)
        return hero

    def change_groups(self, plan):
        """The settings by where they show: what changes, then what is
        already set, folded away."""
        by_section = {section: [] for section in SECTIONS}
        for r in plan["settings"]:
            label, section = label_for(r)
            by_section[section].append((label, r))
        for section, rows in by_section.items():
            if not rows:
                continue
            title, description = SECTIONS[section]
            changed = [(label, r) for label, r in rows if r["changed"]]
            same = [(label, r) for label, r in rows if not r["changed"]]
            group = Adw.PreferencesGroup(
                title=title, description=f"{description}. " + (
                    f"{len(changed)} change{'s' if len(changed) != 1 else ''}." if changed else "Already set."))
            for label, r in changed:
                row = Adw.ActionRow(title=label, subtitle=f"{human(r['key'], r['current'])}  →  "
                                                          f"{human(r['key'], r['new'])}")
                row.add_prefix(Gtk.Image(icon_name="emblem-synchronizing-symbolic"))
                group.add(row)
            if same:
                fold = Adw.ExpanderRow(title=f"{len(same)} already set" if changed else "Settings",
                                       subtitle=", ".join(label for label, _ in same[:3]) +
                                       ("…" if len(same) > 3 else ""))
                for label, r in same:
                    fold.add_row(Adw.ActionRow(title=label, subtitle=human(r["key"], r["new"])))
                group.add(fold)
            yield group

    def _swap_details(self, page):
        child = self.details.get_first_child()
        if child is not None:
            self.details.remove(child)
        self.details.append(page)

    # -- actions ---------------------------------------------------------
    def confirm_apply(self, card):
        changes = sum(r["changed"] for r in self.current_plan["settings"]) + \
            sum(r["changed"] for r in self.current_plan["extensions"])
        dialog = Adw.AlertDialog(
            heading=f"Apply {card.layout['name']}?",
            body=f"{changes} change{'s' if changes != 1 else ''} take effect immediately. Your current settings "
                 "are saved first, so you can restore them at any time.")
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
        self.refresh_in_use()
        self.show_selected()

    def restore(self, snapshot):
        try:
            self.tool.restore(snapshot, out=lambda *_: None)
        except self.tool.LayoutError as e:
            self.error("Could not restore", str(e))
            return
        self.toasts.add_toast(Adw.Toast(title="Previous settings restored"))
        self.refresh_in_use()
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
