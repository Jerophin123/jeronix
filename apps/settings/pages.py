# SPDX-License-Identifier: GPL-3.0-or-later
"""The pages of JERONIX Settings. BUILDERS maps each page id of
catalog.PAGES to the function that builds its Adw.PreferencesPage; the
larger areas live in pages_network.py, pages_devices.py and
pages_people.py.

ctx (see settings.SettingsWindow) gives a page the window, ctx.toast(text)
and ctx.show(page_id).
"""

import configparser
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from jeronix_common import VERSION, paths, shell  # noqa: E402

from . import catalog, system  # noqa: E402
from . import pages_devices as devices  # noqa: E402
from . import pages_network as network  # noqa: E402
from . import pages_people as people  # noqa: E402
from . import widgets as W  # noqa: E402

DOCK, PANEL = "jeronix-dock@jeronix", "jeronix-panel@jeronix"
DOCK_SCHEMA = "org.gnome.shell.extensions.jeronix-dock"
PANEL_SCHEMA = "org.gnome.shell.extensions.jeronix-panel"
# Switches on the Desktop & Taskbar page (keys of DOCK_SCHEMA).
TASKBAR_ITEMS = (
    ("show-start-button", "Start button"),
    ("show-search-button", "Search box"),
    ("show-task-view-button", "Task View button"),
    ("system-tray", "Control Center and clock in the taskbar"),
    ("hide-top-bar", "Hide the top bar while the taskbar has the clock"),
    ("show-running", "Show running apps"),
    ("show-previews", "Window previews on hover"),
    ("magnify", "Magnify icons under the pointer"),
    ("show-apps-button", "Applications button at the end"),
    ("hide-overview-dash", "Task View shows only windows and workspaces"),
)
# The widgets the taskbar's live updates open (live-widgets), in their default order.
LIVE_WIDGETS = (("clock", "Clock and calendar", None), ("timer", "Timer", "Quick timers and focus sessions"),
                ("media", "Now Playing", "When music or video plays"),
                ("weather", "Weather", "When GNOME Weather is installed and has a location"),
                ("system", "System", "Processor, memory and disk use"),
                ("battery", "Battery", "On computers with a battery"))
# What the live updates show (live-activities), in the order Settings lists them.
LIVE_ACTIVITIES = (
    ("media", "Music and video", "What is playing, with play and pause"),
    ("timers", "Timers and stopwatch", "Focus sessions, and the timers and stopwatch of Clocks: time, pause and stop"),
    ("recording", "Screen recording", "Its time, with a stop button"),
    ("privacy", "Microphone and camera in use", "And which apps are using them"),
    ("downloads", "Downloads", "While they download, and when they finish"),
    ("levels", "Volume, brightness and microphone", "When they change, or the microphone is muted"),
    ("notifications", "Notifications", "New ones for a moment, and how many are waiting"),
    ("battery", "Battery", "Charger plugged in or out, and when the battery runs low"),
    ("network", "Network", "Connected, switched or offline"),
    ("keyboard", "Keyboard", "Caps Lock, and the keyboard layout switched to"),
    ("stay-awake", "Stay Awake", "While the screen is kept on"),
    ("do-not-disturb", "Do Not Disturb", "While notifications are silenced"),
    ("workspaces", "Workspaces", "The workspace switched to"),
)
ACCENTS = (("blue", "Blue"), ("teal", "Teal"), ("green", "Green"), ("yellow", "Yellow"), ("orange", "Orange"),
           ("red", "Red"), ("pink", "Pink"), ("purple", "Purple"), ("slate", "Slate"))
# Default Apps: what each choice sets, as GNOME Settings does.
DEFAULT_APPS = (
    ("Web", ("x-scheme-handler/http", "x-scheme-handler/https", "text/html")),
    ("Mail", ("x-scheme-handler/mailto",)),
    ("Calendar", ("text/calendar",)),
    ("Music", ("audio/x-vorbis+ogg", "audio/mpeg", "audio/flac", "audio/x-wav")),
    ("Video", ("video/x-ogm+ogg", "video/mp4", "video/x-matroska", "video/webm")),
    ("Photos", ("image/jpeg", "image/png", "image/gif", "image/webp")),
)
SEARCH_PROVIDERS = (Path("/usr/share/gnome-shell/search-providers"),)


# -- Notifications ------------------------------------------------------------------------

def notifications_page(ctx):
    page = W.page("notifications")
    g = W.group(page, description="Do Not Disturb is also in the Control Center.")
    W.switch(g, W.settings("org.gnome.desktop.notifications", "show-banners"),
             "show-banners", "Do Not Disturb", "Hide notification banners; they still collect in the list", invert=True)
    W.switch(g, W.settings("org.gnome.desktop.notifications", "show-in-lock-screen"),
             "show-in-lock-screen", "Show on the lock screen")
    parent = W.settings("org.gnome.desktop.notifications", "application-children")
    apps = W.group(page, "Apps", "Apps appear here after they first send a notification.")
    if parent is None:
        return page
    schema = "org.gnome.desktop.notifications.application"
    shown = 0
    for child in sorted(parent.get_strv("application-children")):
        s = W.relocatable(schema, f"/org/gnome/desktop/notifications/application/{child}/",
                          "application-id", "enable")
        if s is None:
            continue
        info = shell.desktop_app_info(s.get_string("application-id"))
        if info is None:
            continue  # the app has been removed
        row = Adw.SwitchRow(title=info.get_display_name(), use_markup=False)
        row.add_prefix(W.app_icon(info.get_icon(), 24))
        s.bind("enable", row, "active", Gio.SettingsBindFlags.DEFAULT)
        apps.add(row)
        shown += 1
    if not shown:
        apps.add(W.plain_row("No apps yet"))
    return page


# -- Appearance and Wallpaper -----------------------------------------------------------------

def appearance_page(ctx):
    page = W.page("appearance")
    interface = W.settings("org.gnome.desktop.interface", "color-scheme")
    if interface:
        g = W.group(page, "Appearance")
        g.add(_style_cards(interface))
    accent = W.group(page, "Accent color", "Used by apps for buttons, selections and switches.")
    W.choice(accent, W.settings("org.gnome.desktop.interface", "accent-color"),
             "accent-color", "Accent color", ACCENTS)
    text = W.group(page, "Text")
    _text_size(text)
    _font_row(text, W.settings("org.gnome.desktop.interface", "font-name"),
              "font-name", "Interface font")
    _font_row(text, W.settings("org.gnome.desktop.interface", "document-font-name"),
              "document-font-name", "Document font")
    _font_row(text, W.settings("org.gnome.desktop.interface", "monospace-font-name"),
              "monospace-font-name", "Monospace font")
    W.choice(text, W.settings("org.gnome.desktop.interface", "font-antialiasing"),
             "font-antialiasing", "Smoothing", [("grayscale", "Standard (grayscale)"),
                                                ("rgba", "Subpixel (for LCD screens)"), ("none", "None")])
    theme = W.group(page, "JERONIX look")
    W.extension_switch(theme, "JERONIX shell theme", "Graphite, ivory and blue for menus, the Control Center "
                       "and notifications", "jeronix-shell-theme@jeronix")
    W.link(theme, "Layouts", lambda: W.launch("io.jeronix.LayoutStudio.desktop"),
           subtitle="Pure, Classic or Studio, in Layout Studio", icon="view-dual-symbolic")
    W.link(theme, "Wallpaper", lambda: ctx.show("wallpaper"), icon="preferences-desktop-wallpaper-symbolic")
    return page


def _font_row(g, s, key, title):
    if s is None:
        return None
    row = Adw.ActionRow(title=title)
    current = s.get_string(key)
    description = _font_description(current)
    button = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER, use_font=True)
    button.set_font_desc(description)
    # GTK shows "None" for a family that is not installed; say what it is.
    if description.get_family() and description.get_family().lower() not in _installed_families():
        row.set_subtitle(f"{current} is not installed; choose another font")
    button.connect("notify::font-desc", lambda b, _: (s.set_string(key, b.get_font_desc().to_string()),
                                                      row.set_subtitle("")))
    row.add_suffix(button)
    g.add(row)
    return row


def _installed_families():
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    return {f.get_name().lower() for f in PangoCairo.FontMap.get_default().list_families()}


def _font_description(text):
    gi.require_version("Pango", "1.0")
    from gi.repository import Pango
    return Pango.FontDescription.from_string(text)


def _text_size(g):
    # A double key with a few sensible steps (GNOME's own value is 1.0).
    s = W.settings("org.gnome.desktop.interface", "text-scaling-factor")
    if s is None:
        return None
    sizes = [1.0, 1.1, 1.25, 1.5]
    labels = {1.0: "Default", 1.1: "Large", 1.25: "Larger", 1.5: "Largest"}
    current = round(s.get_double("text-scaling-factor"), 2)
    if current not in sizes:
        sizes.append(current)
    names = [labels.get(v, f"{round(v * 100)}%") for v in sizes]
    row = Adw.ComboRow(title="Text size", model=Gtk.StringList.new(names))
    row.set_selected(sizes.index(current))
    row.connect("notify::selected", lambda r, _: s.set_double("text-scaling-factor", sizes[r.get_selected()]))
    g.add(row)
    return row


def _style_preview(mode):
    """A miniature desktop (surface, window with an accent, taskbar), drawn
    with plain boxes; colors come from settings.settings_css()."""
    preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=148, height_request=96)
    preview.add_css_class("jeronix-style-preview")
    preview.add_css_class(f"jeronix-style-{mode}")
    window = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=92, height_request=54,
                     halign=Gtk.Align.START, valign=Gtk.Align.START, vexpand=True, margin_start=18, margin_top=13)
    window.add_css_class("jeronix-style-window")
    accent = Gtk.Box(width_request=32, height_request=8, halign=Gtk.Align.START, margin_start=9, margin_top=9)
    accent.add_css_class("jeronix-style-accent")
    window.append(accent)
    preview.append(window)
    bar = Gtk.Box(height_request=15)
    bar.add_css_class("jeronix-style-bar")
    preview.append(bar)
    return preview


def _style_cards(interface):
    """Light and Dark as two picture cards, macOS style."""
    box = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=12)
    buttons = {}
    group = None
    for value, title, mode in (("prefer-light", "Light", "light"), ("prefer-dark", "Dark", "dark")):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        frame = Gtk.Frame(child=_style_preview(mode))
        card.append(frame)
        button = Gtk.CheckButton(label=title, group=group, halign=Gtk.Align.CENTER)
        group = group or button
        card.append(button)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_, b=button: b.set_active(True))
        frame.add_controller(click)
        buttons[value] = button
        box.append(card)

    def load(*_):
        value = interface.get_string("color-scheme")
        buttons["prefer-dark" if value == "prefer-dark" else "prefer-light"].set_active(True)

    load()
    for value, button in buttons.items():
        button.connect("toggled", lambda b, v=value: b.get_active() and
                       interface.get_string("color-scheme") != v and interface.set_string("color-scheme", v))
    interface.connect("changed::color-scheme", load)
    return box


def wallpaper_page(ctx):
    page = W.page("wallpaper")
    background = W.settings("org.gnome.desktop.background", "picture-uri", "picture-uri-dark")
    g = W.group(page, "JERONIX wallpapers", "Light is used in light mode, Dark in dark mode.")
    if background is None:
        g.add(W.plain_row("Wallpaper settings are not available"))
        return page
    try:
        tool = paths.layout_tool()
        files = [(tool.asset_path("wallpaper-light"), "Light"), (tool.asset_path("wallpaper-dark"), "Dark")]
    except Exception:  # noqa: BLE001 - layout tool missing: no shipped wallpapers to show
        files = []
    shipped = [(Path(f), name) for f, name in files if Path(f).is_file()]
    if shipped:
        box = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, margin_top=12, margin_bottom=12)
        for path, name in shipped:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            picture = Gtk.Picture.new_for_filename(str(path))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_size_request(176, 99)
            card.append(Gtk.Frame(child=picture))
            card.append(Gtk.Label(label=name))
            box.append(card)
        g.add(box)
        named = {name: path for path, name in shipped}

        def use_shipped():
            if "Light" in named:
                background.set_string("picture-uri", named["Light"].as_uri())
            if "Dark" in named:
                background.set_string("picture-uri-dark", named["Dark"].as_uri())
            ctx.toast("JERONIX wallpapers set")
        W.button_row(g, "Use the JERONIX wallpapers", use_shipped, "emblem-ok-symbolic")
    else:
        g.add(W.plain_row("The JERONIX wallpapers are not installed"))

    own = W.group(page, "Your picture")

    def set_picture(path):
        uri = Gio.File.new_for_path(path).get_uri()
        background.set_string("picture-uri", uri)
        background.set_string("picture-uri-dark", uri)
        ctx.toast("Wallpaper changed")
    W.button_row(own, "Choose a picture…", lambda: W.choose_file(ctx.window, "Choose a wallpaper", set_picture,
                                                                 images=True), "folder-pictures-symbolic")
    W.choice(own, W.settings("org.gnome.desktop.background", "picture-options"),
             "picture-options", "Fit", [("zoom", "Fill the screen"), ("scaled", "Fit to screen"),
                                        ("centered", "Center"), ("spanned", "Span displays")])
    return page


# -- Control Center, Desktop & Taskbar, Start Menu --------------------------------------------------

def control_center_page(ctx):
    page = W.page("control-center")
    s = W.extension_settings(DOCK, DOCK_SCHEMA, "control-center-modules", "control-center-reduce-transparency")
    intro = W.group(page, description="Click the status icons in the taskbar, or press Super+S, to open the "
                    "Control Center. Choose what it shows and in which order. Modules a computer does not have "
                    "(no Bluetooth, no battery...) are left out by themselves.")
    if s is None:
        intro.add(W.plain_row("The JERONIX taskbar is not installed"))
        return page
    look = W.group(page, "Look")
    W.switch(look, s, "control-center-reduce-transparency", "Reduce transparency",
             "A solid background instead of a translucent one")
    modules = W.DynamicGroup(page, "Modules")
    reset = W.text_button("Reset", lambda: s.reset("control-center-modules"))
    reset.add_css_class("flat")
    modules.group.set_header_suffix(reset)
    names = {m: (title, note) for m, title, note in catalog.CONTROL_CENTER_MODULES}

    def refresh(*_):
        modules.clear()
        enabled = [m for m in s.get_strv("control-center-modules") if m in names]
        ordered = enabled + [m for m in names if m not in enabled]
        for module in ordered:
            title, note = names[module]
            row = Adw.SwitchRow(title=title, subtitle=note or None, active=module in enabled)
            row.connect("notify::active", lambda r, _, m=module: s.set_strv(
                "control-center-modules", catalog.toggle_module(s.get_strv("control-center-modules"), m,
                                                                r.get_active())))
            if module in enabled:
                index = enabled.index(module)
                up = W.flat_button("go-up-symbolic", "Move up", lambda i=index: s.set_strv(
                    "control-center-modules", catalog.move_item(enabled, i, -1)))
                down = W.flat_button("go-down-symbolic", "Move down", lambda i=index: s.set_strv(
                    "control-center-modules", catalog.move_item(enabled, i, 1)))
                up.set_sensitive(index > 0)
                down.set_sensitive(index < len(enabled) - 1)
                row.add_suffix(up)
                row.add_suffix(down)
            modules.add(row)

    s.connect("changed::control-center-modules", refresh)
    refresh()
    return page


def desktop_page(ctx):
    page = W.page("desktop")
    s = W.extension_settings(DOCK, DOCK_SCHEMA, "style", "alignment", "position", "behavior", "icon-size")
    bar = W.group(page, "Taskbar")
    W.extension_switch(bar, "JERONIX taskbar", "Start, search, apps, Control Center and clock", DOCK)
    if s:
        W.choice(bar, s, "style", "Style", [("modules", "Expandable modules"), ("taskbar", "Full-width taskbar"),
                                            ("floating", "Floating dock")])
        W.choice(bar, s, "alignment", "Alignment", [("center", "Centered"), ("start", "Left")])
        W.choice(bar, s, "position", "Position", [("bottom", "Bottom"), ("left", "Left"), ("right", "Right")])
        W.choice(bar, s, "behavior", "Visibility", [("always", "Always visible"),
                                                     ("intellihide", "Hide when a window overlaps"),
                                                     ("autohide", "Show at the screen edge")])
        size = Adw.SpinRow.new_with_range(24, 72, 4)
        size.set_title("Icon size")
        size.set_subtitle("Icons shrink automatically when many apps are open")
        s.bind("icon-size", size, "value", Gio.SettingsBindFlags.DEFAULT)
        bar.add(size)
        items = W.group(page, "Taskbar items")
        for key, title in TASKBAR_ITEMS:
            if s.props.settings_schema.has_key(key):
                W.switch(items, s, key, title)
        _live_updates_group(page)
    panel = W.extension_settings(PANEL, PANEL_SCHEMA, "show-menu-label", "show-workspaces",
                                 "show-window-context", "hide-activities")
    top = W.group(page, "Top bar", "Used by the Classic and Studio layouts.")
    W.extension_switch(top, "JERONIX top bar", "The JERONIX menu, workspaces and focused app", PANEL)
    if panel:
        W.switch(top, panel, "show-menu-label", "Show the JERONIX name")
        W.switch(top, panel, "show-workspaces", "Show workspaces")
        W.switch(top, panel, "show-window-context", "Show the focused app")
        W.switch(top, panel, "hide-activities", "Replace Activities")
    windows = W.group(page, "Windows")
    W.choice(windows, W.settings("org.gnome.desktop.wm.preferences", "button-layout"),
             "button-layout", "Title bar buttons", [("appmenu:close", "Close only"),
                                                    ("appmenu:minimize,close", "Minimize and close"),
                                                    ("appmenu:minimize,maximize,close", "Minimize, maximize and close")])
    W.choice(windows, W.settings("org.gnome.desktop.wm.preferences", "action-double-click-titlebar"),
             "action-double-click-titlebar", "Double-click a title bar", [
                 ("toggle-maximize", "Maximize"), ("minimize", "Minimize"), ("none", "Nothing")])
    W.switch(windows, W.settings("org.gnome.mutter", "center-new-windows"),
             "center-new-windows", "Open new windows in the center")
    W.link(W.group(page), "Layout Studio", lambda: W.launch("io.jeronix.LayoutStudio.desktop"),
           subtitle="Switch between the Pure, Classic and Studio layouts", icon="view-dual-symbolic")
    return page


def _live_updates_group(page):
    """Live updates at the left end of the taskbar, and the widgets they open
    (not shown with an older taskbar that has neither)."""
    s = W.extension_settings(DOCK, DOCK_SCHEMA, "live-updates", "live-widgets")
    if s is None:
        return
    g = W.group(page, "Live updates and widgets",
                "The left end of the taskbar shows what is going on: music, a screen recording, volume and "
                "brightness, notifications, charging. Click it for the widgets.")
    W.switch(g, s, "live-updates", "Live updates and widgets")
    island = W.extension_settings(DOCK, DOCK_SCHEMA, "live-colors", "live-expand")
    if island:
        W.choice(g, island, "live-colors", "Colors", [("dynamic", "Follow what is going on"),
                                                     ("accent", "Accent color"), ("neutral", "No color")],
                 subtitle="Red while recording, orange for a timer, the album's color for music")
        W.switch(g, island, "live-expand", "Expand on hover",
                 "More controls under the pointer: next track, a minute more, quick actions")
    widgets = W.DynamicGroup(page, "Widgets")
    reset = W.text_button("Reset", lambda: s.reset("live-widgets"))
    reset.add_css_class("flat")
    widgets.group.set_header_suffix(reset)

    def refresh(*_):
        widgets.clear()
        names = {i: (t, note) for i, t, note in LIVE_WIDGETS}
        shown = [w for w in s.get_strv("live-widgets") if w in names]
        order = shown + [i for i in names if i not in shown]
        for widget in order:
            title, note = names[widget]
            row = Adw.SwitchRow(title=title, subtitle=note or "", active=widget in shown)
            row.connect("notify::active", lambda r, _, w=widget: s.set_strv(
                "live-widgets", catalog.toggle_in_order(s.get_strv("live-widgets"), w, r.get_active(),
                                                        [i for i, _, _ in LIVE_WIDGETS])))
            if widget in shown:
                index = shown.index(widget)
                up = W.flat_button("go-up-symbolic", "Move up", lambda i=index: s.set_strv(
                    "live-widgets", catalog.move_item(shown, i, -1)))
                down = W.flat_button("go-down-symbolic", "Move down", lambda i=index: s.set_strv(
                    "live-widgets", catalog.move_item(shown, i, 1)))
                up.set_sensitive(index > 0)
                down.set_sensitive(index < len(shown) - 1)
                row.add_suffix(up)
                row.add_suffix(down)
            widgets.add(row)

    s.connect("changed::live-widgets", refresh)
    s.bind("live-updates", widgets.group, "sensitive", Gio.SettingsBindFlags.GET)
    refresh()
    _live_activities_group(page)


def _live_activities_group(page):
    """Which activities the live updates show (each can be turned off)."""
    s = W.extension_settings(DOCK, DOCK_SCHEMA, "live-updates", "live-activities")
    if s is None:
        return
    g = W.group(page, "Show in live updates", "Scroll over the live updates to go through everything going "
                "on; the widgets list it all with its controls.")
    s.bind("live-updates", g, "sensitive", Gio.SettingsBindFlags.GET)
    order = [i for i, _, _ in LIVE_ACTIVITIES]
    rows = {}

    def load(*_):
        on = set(s.get_strv("live-activities"))
        for activity, row in rows.items():
            if row.get_active() != (activity in on):
                row.set_active(activity in on)

    def toggle(row, _, activity):
        current = s.get_strv("live-activities")
        wanted = catalog.toggle_in_order(current, activity, row.get_active(), order)
        if wanted != [a for a in current if a in order]:
            s.set_strv("live-activities", wanted)

    for activity, title, note in LIVE_ACTIVITIES:
        row = Adw.SwitchRow(title=title, subtitle=note)
        rows[activity] = row
        g.add(row)
    load()
    for activity, row in rows.items():
        row.connect("notify::active", toggle, activity)
    s.connect("changed::live-activities", load)


def start_page(ctx):
    page = W.page("start")
    s = W.extension_settings(DOCK, DOCK_SCHEMA, "start-pinned-apps", "start-hidden-apps", "super-key-start-menu")
    if s is None:
        W.group(page).add(W.plain_row("The JERONIX taskbar is not installed"))
        return page
    g = W.group(page)
    W.switch(g, s, "super-key-start-menu", "Super opens Start", "Off: Super opens Task View")

    pinned = W.DynamicGroup(page, "Pinned", "To pin an app, right-click it in Start → All apps and choose "
                            "Pin to Start.")
    hidden = W.DynamicGroup(page, "Hidden from Start", "These apps never appear in Start or its search.")
    reset = W.text_button("Reset", lambda: s.reset("start-pinned-apps"))
    reset.add_css_class("flat")
    reset.set_tooltip_text("Restore the default pinned apps")
    pinned.group.set_header_suffix(reset)

    def app_row(app_id, info):
        row = W.plain_row(info.get_display_name() if info else app_id)
        row.add_prefix(W.app_icon(info.get_icon() if info else None))
        return row

    def refresh(*_):
        pinned.clear()
        hidden.clear()
        ids = list(s.get_strv("start-pinned-apps"))
        hidden_ids = list(s.get_strv("start-hidden-apps"))
        infos = {app_id: shell.desktop_app_info(app_id) for app_id in ids + hidden_ids}
        visible = [i for i in ids if infos.get(i) and i not in hidden_ids]
        if not visible:
            pinned.note("Nothing is pinned")
        for index, app_id in enumerate(visible):
            row = app_row(app_id, infos[app_id])
            up = W.flat_button("go-up-symbolic", "Move up",
                               lambda a=app_id: s.set_strv("start-pinned-apps",
                                                           catalog.move_among(ids, visible, a, -1)))
            down = W.flat_button("go-down-symbolic", "Move down",
                                 lambda a=app_id: s.set_strv("start-pinned-apps",
                                                             catalog.move_among(ids, visible, a, 1)))
            up.set_sensitive(index > 0)
            down.set_sensitive(index < len(visible) - 1)
            remove = W.flat_button("list-remove-symbolic", "Unpin from Start",
                                   lambda a=app_id: s.set_strv("start-pinned-apps", [i for i in ids if i != a]))
            for b in (up, down, remove):
                row.add_suffix(b)
            pinned.add(row)
        hidden.group.set_visible(bool(hidden_ids))
        for app_id in hidden_ids:
            row = app_row(app_id, infos.get(app_id))
            row.add_suffix(W.text_button("Show", lambda a=app_id: s.set_strv(
                "start-hidden-apps", [i for i in hidden_ids if i != a])))
            hidden.add(row)

    s.connect("changed::start-pinned-apps", refresh)
    s.connect("changed::start-hidden-apps", refresh)
    refresh()
    return page


# -- Multitasking and Accessibility -------------------------------------------------------------

def multitasking_page(ctx):
    page = W.page("multitasking")
    general = W.group(page, "General")
    W.switch(general, W.settings("org.gnome.desktop.interface", "enable-hot-corners"),
             "enable-hot-corners", "Hot corner", "Touch the top-left corner to open Task View")
    W.switch(general, W.settings("org.gnome.mutter", "edge-tiling"),
             "edge-tiling", "Snap windows to screen edges", "Drag a window to an edge to fill half the screen")
    spaces = W.group(page, "Workspaces")
    dynamic = W.settings("org.gnome.mutter", "dynamic-workspaces")
    W.switch(spaces, W.settings("org.gnome.mutter", "dynamic-workspaces"),
             "dynamic-workspaces", "Add workspaces as needed", "Off: a fixed number of workspaces")
    count = W.settings("org.gnome.desktop.wm.preferences", "num-workspaces")
    if count is not None:
        row = Adw.SpinRow.new_with_range(1, 36, 1)
        row.set_title("Number of workspaces")
        count.bind("num-workspaces", row, "value", Gio.SettingsBindFlags.DEFAULT)
        spaces.add(row)
        if dynamic is not None:
            dynamic.bind("dynamic-workspaces", row, "sensitive", Gio.SettingsBindFlags.INVERT_BOOLEAN |
                         Gio.SettingsBindFlags.GET)
    W.switch(spaces, W.settings("org.gnome.mutter", "workspaces-only-on-primary"),
             "workspaces-only-on-primary", "Workspaces on the primary display only",
             "Other displays keep their windows when you switch")
    apps = W.group(page, "App switching")
    W.switch(apps, W.settings("org.gnome.shell.app-switcher", "current-workspace-only"),
             "current-workspace-only", "Alt+Tab shows only this workspace's apps")
    return page


def accessibility_page(ctx):
    page = W.page("accessibility")
    seeing = W.group(page, "Seeing")
    W.switch(seeing, W.settings("org.gnome.desktop.a11y.interface", "high-contrast"),
             "high-contrast", "High contrast")
    W.switch(seeing, W.settings("org.gnome.desktop.interface", "enable-animations"),
             "enable-animations", "Reduce motion", "Turn off animations", invert=True)
    W.switch(seeing, W.settings("org.gnome.desktop.interface", "overlay-scrolling"),
             "overlay-scrolling", "Always show scroll bars", invert=True)
    W.choice(seeing, W.settings("org.gnome.desktop.interface", "cursor-size"),
             "cursor-size", "Pointer size", [24, 32, 48, 64, 96],
             label=lambda v: {24: "Default", 32: "Medium", 48: "Large", 64: "Larger", 96: "Largest"}.get(v, str(v)))
    W.switch(seeing, W.settings("org.gnome.desktop.interface", "locate-pointer"),
             "locate-pointer", "Locate the pointer with Ctrl")
    zoom = W.group(page, "Zoom")
    W.switch(zoom, W.settings("org.gnome.desktop.a11y.applications", "screen-magnifier-enabled"),
             "screen-magnifier-enabled", "Zoom", "Magnify the area around the pointer")
    W.scale(zoom, W.settings("org.gnome.desktop.a11y.magnifier", "mag-factor"),
            "mag-factor", "Magnification", 1, 8, 0.25, marks=((1, "1×"), (8, "8×")))
    hearing = W.group(page, "Hearing and reading")
    W.switch(hearing, W.settings("org.gnome.desktop.wm.preferences", "visual-bell"),
             "visual-bell", "Visual alerts", "Flash the screen when an alert sound plays")
    W.switch(hearing, W.settings("org.gnome.desktop.a11y.applications", "screen-reader-enabled"),
             "screen-reader-enabled", "Screen reader", "Reads out what is on the screen (Super+Alt+S)")
    typing = W.group(page, "Typing")
    W.switch(typing, W.settings("org.gnome.desktop.a11y.applications", "screen-keyboard-enabled"),
             "screen-keyboard-enabled", "On-screen keyboard")
    W.switch(typing, W.settings("org.gnome.desktop.a11y.keyboard", "stickykeys-enable"),
             "stickykeys-enable", "Sticky keys", "Press shortcut keys one at a time")
    W.switch(typing, W.settings("org.gnome.desktop.a11y.keyboard", "slowkeys-enable"),
             "slowkeys-enable", "Slow keys", "Keys must be held before they count")
    W.switch(typing, W.settings("org.gnome.desktop.a11y.keyboard", "bouncekeys-enable"),
             "bouncekeys-enable", "Bounce keys", "Ignore fast repeated presses")
    W.switch(typing, W.settings("org.gnome.desktop.a11y.keyboard", "mousekeys-enable"),
             "mousekeys-enable", "Mouse keys", "Move the pointer with the number pad")
    W.switch(typing, W.settings("org.gnome.desktop.a11y", "always-show-universal-access-status"),
             "always-show-universal-access-status", "Show the accessibility menu in the top bar")
    return page


# -- Power, Privacy, Search ------------------------------------------------------------------

def power_page(ctx):
    page = W.page("power")
    battery = system.Battery()
    if battery.present:
        g = W.group(page, "Battery")
        W.info(g, "Charge", battery.summary(), "battery-full-symbolic")
        W.switch(g, W.settings("org.gnome.desktop.interface", "show-battery-percentage"),
                 "show-battery-percentage", "Show the percentage in the taskbar")
        W.switch(g, W.settings("org.gnome.settings-daemon.plugins.power", "power-saver-profile-on-low-battery"),
                 "power-saver-profile-on-low-battery", "Power Saver on low battery")
    profiles = system.PowerProfiles()
    names = {"power-saver": "Power Saver", "balanced": "Balanced", "performance": "Performance"}
    available = [p for p in profiles.profiles() if p in names]
    if profiles.available and available:
        g = W.group(page, "Power mode")
        row = Adw.ComboRow(title="Mode", model=Gtk.StringList.new([names[p] for p in available]))
        if profiles.active in available:
            row.set_selected(available.index(profiles.active))

        def chosen(r, _):
            wanted = available[r.get_selected()]
            if wanted != profiles.active:
                error = profiles.set_active(wanted)
                if error:
                    ctx.toast(f"Could not change the power mode: {error}")
        row.connect("notify::selected", chosen)
        g.add(row)
    screen = W.group(page, "Screen")
    W.choice(screen, W.settings("org.gnome.desktop.session", "idle-delay"),
             "idle-delay", "Turn the screen off after", catalog.BLANK_SCREEN, label=catalog.duration_label)
    W.switch(screen, W.settings("org.gnome.settings-daemon.plugins.power", "idle-dim"),
             "idle-dim", "Dim the screen before turning it off")
    sleep = W.group(page, "Sleep")
    W.choice(sleep, W.settings("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type"),
             "sleep-inactive-ac-type", "When plugged in and idle", [("suspend", "Suspend"), ("nothing", "Stay on")])
    W.choice(sleep, W.settings("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout"),
             "sleep-inactive-ac-timeout", "Suspend after (plugged in)", catalog.SUSPEND_AFTER,
             label=catalog.duration_label)
    if battery.present:
        W.choice(sleep, W.settings("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type"),
                 "sleep-inactive-battery-type", "On battery and idle", [("suspend", "Suspend"), ("nothing", "Stay on")])
        W.choice(sleep, W.settings("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout"),
                 "sleep-inactive-battery-timeout", "Suspend after (on battery)", catalog.SUSPEND_AFTER,
                 label=catalog.duration_label)
    W.choice(sleep, W.settings("org.gnome.settings-daemon.plugins.power", "power-button-action"),
             "power-button-action", "Power button", [("interactive", "Ask what to do"), ("suspend", "Suspend"),
                                                     ("hibernate", "Hibernate"), ("nothing", "Do nothing")])
    return page


def privacy_page(ctx):
    page = W.page("privacy")
    lock = W.group(page, "Lock screen")
    W.switch(lock, W.settings("org.gnome.desktop.screensaver", "lock-enabled"),
             "lock-enabled", "Lock when the screen turns off")
    W.choice(lock, W.settings("org.gnome.desktop.screensaver", "lock-delay"),
             "lock-delay", "Lock after the screen turns off", catalog.LOCK_DELAY,
             label=lambda v: "Immediately" if v == 0 else catalog.duration_label(v))
    W.switch(lock, W.settings("org.gnome.desktop.notifications", "show-in-lock-screen"),
             "show-in-lock-screen", "Show notifications on the lock screen")
    devices = W.group(page, "Location, camera and microphone")
    W.switch(devices, W.settings("org.gnome.system.location", "enabled"),
             "enabled", "Location services", "Apps may ask for your approximate location")
    W.switch(devices, W.settings("org.gnome.desktop.privacy", "disable-camera"),
             "disable-camera", "Camera", "Off: no app can use a camera", invert=True)
    W.switch(devices, W.settings("org.gnome.desktop.privacy", "disable-microphone"),
             "disable-microphone", "Microphone", "Off: no app can use a microphone", invert=True)
    W.switch(devices, W.settings("org.gnome.desktop.privacy", "usb-protection"),
             "usb-protection", "USB protection", "Block new USB devices while the screen is locked")
    history = W.group(page, "History")
    W.switch(history, W.settings("org.gnome.desktop.privacy", "remember-recent-files"),
             "remember-recent-files", "Remember recently used files")
    W.choice(history, W.settings("org.gnome.desktop.privacy", "recent-files-max-age"),
             "recent-files-max-age", "Keep the history for", [1, 7, 30, -1],
             label=lambda v: "Forever" if v < 0 else f"{v} day{'s' if v != 1 else ''}")

    def clear_history():
        Gtk.RecentManager.get_default().purge_items()
        ctx.toast("History cleared")
    W.button_row(history, "Clear the history now", clear_history, "edit-clear-all-symbolic")
    files = W.group(page, "Trash and temporary files")
    W.switch(files, W.settings("org.gnome.desktop.privacy", "remove-old-trash-files"),
             "remove-old-trash-files", "Empty the trash automatically")
    W.switch(files, W.settings("org.gnome.desktop.privacy", "remove-old-temp-files"),
             "remove-old-temp-files", "Delete old temporary files")
    W.choice(files, W.settings("org.gnome.desktop.privacy", "old-files-age"),
             "old-files-age", "After", [1, 7, 14, 30], label=lambda v: f"{v} day{'s' if v != 1 else ''}")
    reports = W.group(page, "Diagnostics")
    W.switch(reports, W.settings("org.gnome.desktop.privacy", "report-technical-problems"),
             "report-technical-problems", "Report problems", "Send anonymous crash reports")
    return page


def _search_providers():
    """[(desktop_id, name, default_disabled)] of GNOME search providers."""
    found = []
    for directory in SEARCH_PROVIDERS:
        for ini in sorted(directory.glob("*.ini")) if directory.is_dir() else []:
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(ini, encoding="utf-8")
                section = parser["Shell Search Provider"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            desktop_id = section.get("DesktopId")
            info = shell.desktop_app_info(desktop_id) if desktop_id else None
            if info is None:
                continue
            found.append((desktop_id, info.get_display_name(), section.get("DefaultDisabled", "false") == "true"))
    return found


def search_page(ctx):
    page = W.page("search")
    s = W.settings("org.gnome.desktop.search-providers", "disable-external", "disabled", "enabled")
    g = W.group(page, description="Task View's search can also show results from these apps.")
    if s is None:
        g.add(W.plain_row("Search settings are not available"))
        return page
    W.switch(g, W.settings("org.gnome.desktop.search-providers", "disable-external"),
             "disable-external", "Results from apps", invert=True)
    apps = W.group(page, "Apps")
    for desktop_id, name, default_disabled in _search_providers():
        row = Adw.SwitchRow(title=name, use_markup=False)

        def on(did=desktop_id, dd=default_disabled):
            return did in s.get_strv("enabled") if dd else did not in s.get_strv("disabled")

        def toggle(r, _, did=desktop_id, dd=default_disabled):
            key = "enabled" if dd else "disabled"
            ids = [i for i in s.get_strv(key) if i != did]
            if r.get_active() == dd:  # enabling a default-off provider, or disabling a default-on one
                ids.append(did)
            s.set_strv(key, ids)
        row.set_active(on())
        row.connect("notify::active", toggle)
        apps.add(row)
    return page


# -- Mouse, Default Apps, About ------------------------------------------------------------------

def mouse_page(ctx):
    page = W.page("mouse")
    vm = system.virtual_machine()
    # In a virtual machine the host moves the pointer to absolute positions,
    # so speed and acceleration have nothing to act on.
    mouse = W.group(page, "Mouse", f"Running in a virtual machine ({vm}): the host controls pointer speed and "
                    "acceleration, so those settings take effect only on real hardware." if vm else None)
    W.scale(mouse, W.settings("org.gnome.desktop.peripherals.mouse", "speed"),
            "speed", "Pointer speed", -1, 1, 0.05, marks=((-1, "Slow"), (1, "Fast")))
    W.switch(mouse, W.settings("org.gnome.desktop.peripherals.mouse", "natural-scroll"),
             "natural-scroll", "Natural scrolling", "Content follows your finger")
    W.switch(mouse, W.settings("org.gnome.desktop.peripherals.mouse", "left-handed"),
             "left-handed", "Swap the left and right buttons")
    W.choice(mouse, W.settings("org.gnome.desktop.peripherals.mouse", "accel-profile"),
             "accel-profile", "Acceleration", [("default", "Default"), ("adaptive", "Adaptive"),
                                               ("flat", "Off (flat)")])
    pad = W.group(page, "Touchpad")
    if system.input_devices_with("ID_INPUT_TOUCHPAD") == 0:
        pad.add(W.plain_row("No touchpad", "Touchpad settings appear when this computer has one."))
        _general_pointer_group(page)
        return page
    W.scale(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "speed"),
            "speed", "Pointer speed", -1, 1, 0.05, marks=((-1, "Slow"), (1, "Fast")))
    W.switch(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "tap-to-click"),
             "tap-to-click", "Tap to click")
    W.switch(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "natural-scroll"),
             "natural-scroll", "Natural scrolling", "Content follows your fingers")
    W.switch(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "two-finger-scrolling-enabled"),
             "two-finger-scrolling-enabled", "Scroll with two fingers")
    W.switch(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "disable-while-typing"),
             "disable-while-typing", "Ignore the touchpad while typing")
    W.choice(pad, W.settings("org.gnome.desktop.peripherals.touchpad", "click-method"),
             "click-method", "Secondary click", [("fingers", "Two-finger tap or click"),
                                                 ("areas", "Bottom-right corner"), ("default", "Default")])
    _general_pointer_group(page)
    return page


def _general_pointer_group(page):
    general = W.group(page, "General")
    W.switch(general, W.settings("org.gnome.desktop.interface", "gtk-enable-primary-paste"),
             "gtk-enable-primary-paste", "Middle click pastes", "Paste the selected text with the middle button")


def default_apps_page(ctx):
    page = W.page("default-apps")
    g = W.group(page, "Open with")
    for title, types in DEFAULT_APPS:
        apps = Gio.AppInfo.get_recommended_for_type(types[0])
        current = Gio.AppInfo.get_default_for_type(types[0], False)
        if current and current.get_id() not in [a.get_id() for a in apps]:
            apps.insert(0, current)
        if not apps:
            g.add(W.plain_row(title, "No app installed for this"))
            continue
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([a.get_display_name() for a in apps]))
        ids = [a.get_id() for a in apps]
        if current and current.get_id() in ids:
            row.set_selected(ids.index(current.get_id()))

        def chosen(r, _, items=apps, kinds=types, name=title):
            app = items[r.get_selected()]
            try:
                for kind in kinds:
                    app.set_as_default_for_type(kind)
            except GLib.Error as e:
                ctx.toast(f"Could not set the {name.lower()} app: {e.message}")
        row.connect("notify::selected", chosen)
        g.add(row)
    media = W.group(page, "Removable media")
    W.switch(media, W.settings("org.gnome.desktop.media-handling", "autorun-never"),
             "autorun-never", "Ask what to do when media is inserted", "Off: never start apps for media",
             invert=True)
    return page


def about_page(ctx):
    page = W.page("about")
    head = W.group(page)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=12)
    mode = "dark" if Adw.StyleManager.get_default().get_dark() else "light"
    lockup = paths.root() / "design" / "icons" / f"jeronix-lockup-on-{mode}.svg"
    if not lockup.is_file():
        lockup = paths.root() / "branding" / f"jeronix-lockup-on-{mode}.svg"
    if lockup.is_file():
        picture = Gtk.Picture.new_for_filename(str(lockup))
        picture.set_size_request(-1, 72)
        picture.set_can_shrink(True)
        box.append(picture)
    version = Gtk.Label(label=f"Version {VERSION}")
    version.add_css_class("dim-label")
    box.append(version)
    head.add(box)

    from system_info import collect
    facts = collect.collect()
    g = W.group(page, "This computer")
    host = system.Hostname()
    W.info(g, "Name", host.pretty if host.available else system.hostname())
    for key, title in (("Processor", "Processor"), ("Memory", "Memory"), ("Graphics driver", "Graphics"),
                       ("Disk (/)", "Storage"), ("Kernel", "Kernel"), ("GNOME Shell", "Desktop shell"),
                       ("Operating system", "Operating system")):
        W.info(g, title, str(facts.get(key, "unknown")))
    more = W.group(page)
    W.link(more, "Change the device name", lambda: ctx.show("sharing"), icon="computer-symbolic")
    W.link(more, "System report", lambda: W.launch("io.jeronix.SystemInfo.desktop"),
           subtitle="Everything above and more, ready to copy for support", icon="help-about-symbolic")
    W.link(more, "Welcome tour", lambda: W.launch("io.jeronix.Welcome.desktop"), icon="starred-symbolic")
    return page


BUILDERS = {
    "wifi": network.wifi_page, "bluetooth": network.bluetooth_page, "network": network.network_page,
    "notifications": notifications_page, "sound": devices.sound_page,
    "appearance": appearance_page, "wallpaper": wallpaper_page, "control-center": control_center_page,
    "desktop": desktop_page, "start": start_page, "displays": devices.displays_page,
    "multitasking": multitasking_page, "accessibility": accessibility_page,
    "power": power_page, "privacy": privacy_page, "search": search_page,
    "users": people.users_page, "region": people.region_page, "datetime": people.datetime_page,
    "keyboard": people.keyboard_page, "mouse": mouse_page, "printers": devices.printers_page,
    "sharing": people.sharing_page, "default-apps": default_apps_page, "about": about_page,
}
