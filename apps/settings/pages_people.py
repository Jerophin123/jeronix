# SPDX-License-Identifier: GPL-3.0-or-later
"""Users, Language & Region, Date & Time, Keyboard and Sharing pages."""

import os

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import catalog, system  # noqa: E402
from . import widgets as W  # noqa: E402

try:
    gi.require_version("GnomeDesktop", "4.0")
    from gi.repository import GnomeDesktop  # language, country and keyboard layout names
except (ImportError, ValueError):
    GnomeDesktop = None


# -- Users -----------------------------------------------------------------------------------

def users_page(ctx):
    page = W.page("users")
    accounts = system.Accounts()
    if not accounts.available:
        W.group(page).add(W.plain_row("User accounts are not available", "AccountsService is not running."))
        return page
    me_group = W.DynamicGroup(page, "Your account")
    others = W.DynamicGroup(page, "Other users", "Adding, removing and changing other users asks for an "
                                                 "administrator's password.")
    others.group.set_header_suffix(W.flat_button("list-add-symbolic", "Add a user", lambda: add_user()))

    def report(what):
        return lambda error: (ctx.toast(f"{what} failed: {error}" if error else f"{what}: done"),
                              GLib.timeout_add(500, lambda: (refresh(), False)[1]))

    def avatar(user, size=48):
        a = Adw.Avatar(size=size, text=user.real_name, show_initials=True)
        if user.icon_file:
            try:
                a.set_custom_image(Gdk.Texture.new_from_filename(user.icon_file))
            except GLib.Error:
                pass  # unreadable picture: initials instead
        return a

    def refresh():
        me_group.clear()
        others.clear()
        users = accounts.users()
        me = next((u for u in users if u.is_me), None)
        if me:
            row = W.plain_row(me.real_name, f"{me.user_name} · {'Administrator' if me.is_admin else 'Standard'}")
            row.add_prefix(avatar(me))
            row.add_suffix(W.flat_button("camera-photo-symbolic", "Change the picture", lambda: W.choose_file(
                ctx.window, "Choose a picture", lambda path: me.set_icon(path, report("Picture")), images=True)))
            me_group.add(row)
            name = Adw.EntryRow(title="Full name", show_apply_button=True)
            name.set_text(me.real_name)
            name.connect("apply", lambda r: r.get_text().strip() and me.set_real_name(r.get_text().strip(),
                                                                                     report("Name")))
            me_group.add(name)
            password = W.plain_row("Password", "Change the password you use to log in", activatable=True)
            password.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            password.connect("activated", lambda *_: change_password(me))
            me_group.add(password)
            auto = Adw.SwitchRow(title="Log in automatically", active=bool(me.get("AutomaticLogin", False)))
            auto.connect("notify::active", lambda r, _: me.set_automatic_login(r.get_active(),
                                                                               report("Automatic login")))
            me_group.add(auto)
        rest = [u for u in users if not u.is_me]
        if not rest:
            others.note("No other users")
        for user in rest:
            row = W.plain_row(user.real_name, f"{user.user_name} · {'Administrator' if user.is_admin else 'Standard'}")
            row.add_prefix(avatar(user, 36))
            admin = Gtk.Switch(active=user.is_admin, valign=Gtk.Align.CENTER, tooltip_text="Administrator")
            admin.connect("notify::active", lambda s, _, u=user: s.get_active() != u.is_admin and u.set_admin(
                s.get_active(), report("Account type")))
            row.add_suffix(Gtk.Label(label="Admin", valign=Gtk.Align.CENTER))
            row.add_suffix(admin)
            row.add_suffix(W.flat_button("dialog-password-symbolic", "Set a password", lambda u=user:
                                         change_password(u)))
            row.add_suffix(W.flat_button("user-trash-symbolic", "Remove this user", lambda u=user: remove(u)))
            others.add(row)

    def change_password(user):
        def validate(v):
            if len(v["password"]) < 8:
                return "Use at least 8 characters."
            if v["password"] != v["again"]:
                return "The passwords do not match."
            return None
        body = ("GNOME asks for your current password to confirm." if user.is_me
                else f"The new password for {user.real_name}.")
        W.form(ctx.window, "Change password", body,
               [("password", "New password", "", "password"), ("again", "Repeat the new password", "", "password")],
               "Change", lambda v: user.set_password(v["password"], report("Password")), validate)

    def add_user():
        def validate(v):
            if not v["full"].strip():
                return "Enter the person's name."
            problem = catalog.valid_username(v["user"])
            if problem:
                return problem
            if len(v["password"]) < 8:
                return "Use at least 8 characters for the password."
            return None

        def create(v):
            def created(path, error):
                if error:
                    ctx.toast(f"Adding the user failed: {error}")
                    return
                user = system.User(path)
                user.set_password(v["password"], report("New user"))
            accounts.create(v["user"], v["full"].strip(), system.STANDARD, created)
        dialog = W.form(ctx.window, "Add a user", "A standard account. Make it an administrator afterwards if needed.",
                        [("full", "Full name", "", "text"), ("user", "User name", "", "text"),
                         ("password", "Password", "", "password")], "Add", create, validate)
        return dialog

    def remove(user):
        W.confirm(ctx.window, f"Remove {user.real_name}?",
                  "The account is deleted. Their files in the home folder are deleted too.", "Remove",
                  lambda: accounts.delete(user, True, report("Remove user")), True)

    refresh()
    return page


# -- Language & Region ------------------------------------------------------------------------

def _locale_name(locale, kind="language"):
    if GnomeDesktop is None:
        return locale
    name = (GnomeDesktop.get_language_from_locale(locale, None) if kind == "language"
            else GnomeDesktop.get_country_from_locale(locale, None))
    return name or locale


def region_page(ctx):
    page = W.page("region")
    accounts = system.Accounts()
    me = accounts.find(os.getuid()) if accounts.available else None
    locales = sorted(GnomeDesktop.get_all_locales()) if GnomeDesktop else []
    g = W.group(page, "Language", "Used for menus and messages. It changes the next time you log in.")
    if me and locales:
        current = me.get("Language") or os.environ.get("LANG", "")
        row = W.plain_row("Language", _locale_name(current) if current else "System default", activatable=True)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_: W.pick(
            ctx.window, "Language", [(loc, _locale_name(loc), loc) for loc in locales],
            lambda loc: me.set_language(loc, lambda e: ctx.toast(e or "Language changes at the next login"))))
        g.add(row)
    else:
        g.add(W.plain_row("Languages are not available"))
    region = W.settings("org.gnome.system.locale", "region")
    formats = W.group(page, "Formats", "Dates, times, numbers and currency.")
    if region and locales:
        current = region.get_string("region")
        row = W.plain_row("Formats", _locale_name(current, "language") + (
            f" ({_locale_name(current, 'country')})" if current else "") if current else "Same as the language",
            activatable=True)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_: W.pick(
            ctx.window, "Formats",
            [(loc, f"{_locale_name(loc)} ({_locale_name(loc, 'country')})", loc) for loc in locales],
            lambda loc: (region.set_string("region", loc), ctx.toast("Formats change at the next login"))))
        formats.add(row)
    return page


# -- Date & Time ------------------------------------------------------------------------------

def datetime_page(ctx):
    page = W.page("datetime")
    td = system.TimeDate()
    clock = W.group(page, "Time")
    if td.available:
        ntp = Adw.SwitchRow(title="Set the time automatically", subtitle="From the internet",
                            active=bool(td.get("NTP", False)))
        ntp.set_sensitive(bool(td.get("CanNTP", True)))
        ntp.connect("notify::active", lambda r, _: r.get_active() != bool(td.get("NTP", False)) and td.set_ntp(
            r.get_active(), lambda e: ctx.toast(e) if e else None))
        clock.add(ntp)
        manual = W.plain_row("Date and time", "Turn off automatic time to set it by hand", activatable=True)
        manual.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        manual.connect("activated", lambda *_: _set_time_dialog(ctx, td))
        clock.add(manual)

        def sync(*_):
            manual.set_sensitive(not td.get("NTP", False))
        ntp.connect("notify::active", sync)
        td.watch(sync)
        sync()
    zone = W.group(page, "Time zone")
    W.switch(zone, W.settings("org.gnome.desktop.datetime", "automatic-timezone"),
             "automatic-timezone", "Set the time zone automatically", "Uses your location")
    if td.available:
        current = W.plain_row("Time zone", td.get("Timezone") or GLib.TimeZone.new_local().get_identifier(),
                              activatable=True)
        current.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

        def chosen(zone_name):
            td.set_timezone(zone_name, lambda e: ctx.toast(f"Could not change the time zone: {e}" if e
                                                           else f"Time zone: {zone_name}"))
            current.set_subtitle(zone_name)
        current.connect("activated", lambda *_: W.pick(
            ctx.window, "Time zone", [(z, catalog.timezone_parts(z)[1], z) for z in system.TimeDate.zones()],
            chosen, "Search for a city"))
        zone.add(current)
    fmt = W.group(page, "Clock")
    W.choice(fmt, W.settings("org.gnome.desktop.interface", "clock-format"),
             "clock-format", "Time format", [("24h", "24-hour"), ("12h", "AM/PM")])
    W.switch(fmt, W.settings("org.gnome.desktop.interface", "clock-show-weekday"),
             "clock-show-weekday", "Show the weekday")
    W.switch(fmt, W.settings("org.gnome.desktop.interface", "clock-show-date"),
             "clock-show-date", "Show the date")
    W.switch(fmt, W.settings("org.gnome.desktop.interface", "clock-show-seconds"),
             "clock-show-seconds", "Show seconds")
    W.switch(fmt, W.settings("org.gnome.desktop.calendar", "show-weekdate"),
             "show-weekdate", "Show week numbers in the calendar")
    return page


def _set_time_dialog(ctx, td):
    dialog = Adw.Dialog(title="Date and time", content_width=360)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                  margin_start=12, margin_end=12)
    now = GLib.DateTime.new_now_local()
    calendar = Gtk.Calendar()
    calendar.select_day(now)
    box.append(calendar)
    times = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
    hours = Gtk.SpinButton.new_with_range(0, 23, 1)
    hours.set_value(now.get_hour())
    minutes = Gtk.SpinButton.new_with_range(0, 59, 1)
    minutes.set_value(now.get_minute())
    times.append(hours)
    times.append(Gtk.Label(label=":"))
    times.append(minutes)
    box.append(times)

    def save():
        day = calendar.get_date()
        moment = GLib.DateTime.new_local(day.get_year(), day.get_month(), day.get_day_of_month(),
                                         int(hours.get_value()), int(minutes.get_value()), 0)
        td.set_time(moment.to_unix() * 1_000_000, lambda e: ctx.toast(f"Could not set the time: {e}" if e
                                                                       else "Time set"))
        dialog.close()
    box.append(W.text_button("Set", save, suggested=True))
    view.set_content(box)
    dialog.set_child(view)
    dialog.present(ctx.window)


# -- Keyboard -------------------------------------------------------------------------------

def keyboard_page(ctx):
    page = W.page("keyboard")
    _input_sources(ctx, page)
    typing = W.group(page, "Typing")
    W.switch(typing, W.settings("org.gnome.desktop.peripherals.keyboard", "repeat"),
             "repeat", "Repeat keys when held")
    W.scale(typing, W.settings("org.gnome.desktop.peripherals.keyboard", "delay"),
            "delay", "Delay before repeating", 150, 1000, 10, marks=((150, "Short"), (1000, "Long")))
    W.scale(typing, W.settings("org.gnome.desktop.peripherals.keyboard", "repeat-interval"),
            "repeat-interval", "Time between repeats", 10, 110, 1, marks=((10, "Fast"), (110, "Slow")))
    _custom_shortcuts(ctx, page)
    shortcuts = W.group(page, "Shortcuts")
    for keys, action in catalog.SHORTCUTS:
        row = Adw.ActionRow(title=action)
        row.add_suffix(W.key_label(keys))
        shortcuts.add(row)
    return page


def _input_sources(ctx, page):
    sources = W.settings("org.gnome.desktop.input-sources", "sources")
    layouts = W.DynamicGroup(page, "Keyboard layouts", "Switch between layouts with Super+Space.")
    if sources is None or GnomeDesktop is None:
        layouts.note("Keyboard layouts are not available")
        return
    xkb = GnomeDesktop.XkbInfo.new()

    def name_of(kind, ident):
        if kind == "xkb":
            ok, display, *_ = xkb.get_layout_info(ident)
            return display if ok else ident
        return f"{ident} (input method)"

    def current():
        return [tuple(s) for s in sources.get_value("sources").unpack()]

    def store(items):
        sources.set_value("sources", GLib.Variant("a(ss)", items))

    def refresh(*_):
        layouts.clear()
        items = current()
        if not items:
            layouts.note("English (US)", "The default layout")
        for i, (kind, ident) in enumerate(items):
            row = W.plain_row(name_of(kind, ident), "Default" if i == 0 else None)
            up = W.flat_button("go-up-symbolic", "Move up", lambda i=i: store(catalog.move_item(current(), i, -1)))
            up.set_sensitive(i > 0)
            row.add_suffix(up)
            remove = W.flat_button("list-remove-symbolic", "Remove", lambda i=i: store(
                [s for j, s in enumerate(current()) if j != i]))
            remove.set_sensitive(len(items) > 1)
            row.add_suffix(remove)
            layouts.add(row)

    def add():
        have = {ident for kind, ident in current() if kind == "xkb"}
        choices = []
        for ident in xkb.get_all_layouts():
            if ident in have:
                continue
            ok, display, short, *_ = xkb.get_layout_info(ident)
            choices.append((ident, display if ok else ident, ident))
        choices.sort(key=lambda c: c[1].lower())
        W.pick(ctx.window, "Add a keyboard layout", choices, lambda ident: store(current() + [("xkb", ident)]),
               "Search for a language or country")

    layouts.group.set_header_suffix(W.flat_button("list-add-symbolic", "Add a layout", add))
    sources.connect("changed::sources", refresh)
    refresh()


def _custom_shortcuts(ctx, page):
    media = W.settings("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings")
    schema = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    group = W.DynamicGroup(page, "Custom shortcuts", "Run a command with a key combination.")
    if media is None:
        group.note("Custom shortcuts are not available")
        return

    def entry(path):
        return W.relocatable(schema, path, "name", "command", "binding")

    def refresh(*_):
        group.clear()
        paths = media.get_strv("custom-keybindings")
        if not paths:
            group.note("No custom shortcuts")
        for path in paths:
            s = entry(path)
            if s is None:
                continue
            row = W.plain_row(s.get_string("name") or "Unnamed", s.get_string("command"), activatable=True)
            row.add_suffix(W.key_label(catalog.accelerator_label(s.get_string("binding"))))
            row.add_suffix(W.flat_button("user-trash-symbolic", "Remove", lambda p=path: remove(p)))
            row.connect("activated", lambda r, p=path: edit(p))
            group.add(row)

    def remove(path):
        s = entry(path)
        if s:
            for key in ("name", "command", "binding"):
                s.reset(key)
        media.set_strv("custom-keybindings", [p for p in media.get_strv("custom-keybindings") if p != path])

    def edit(path=None):
        s = entry(path) if path else None
        _shortcut_dialog(ctx, s.get_string("name") if s else "", s.get_string("command") if s else "",
                         s.get_string("binding") if s else "", lambda name, command, binding: save(
                             path, name, command, binding))

    def save(path, name, command, binding):
        paths = media.get_strv("custom-keybindings")
        if path is None:
            path = catalog.new_custom_keybinding_path(paths)
        s = entry(path)
        if s is None:
            ctx.toast("Custom shortcuts are not available")
            return
        s.set_string("name", name)
        s.set_string("command", command)
        s.set_string("binding", binding)
        if path not in paths:
            media.set_strv("custom-keybindings", paths + [path])

    group.group.set_header_suffix(W.flat_button("list-add-symbolic", "Add a shortcut", lambda: edit(None)))
    media.connect("changed::custom-keybindings", refresh)
    refresh()


def _shortcut_dialog(ctx, name, command, binding, save):
    """Name, command and a key combination captured from the keyboard."""
    dialog = Adw.Dialog(title="Custom shortcut", content_width=420)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    page = Adw.PreferencesPage()
    g = W.group(page)
    name_row = Adw.EntryRow(title="Name")
    name_row.set_text(name)
    command_row = Adw.EntryRow(title="Command")
    command_row.set_text(command)
    g.add(name_row)
    g.add(command_row)
    state = {"binding": binding, "capturing": False}
    keys = W.plain_row("Shortcut", catalog.accelerator_label(binding))
    capture = Gtk.Button(label="Set…", valign=Gtk.Align.CENTER)
    keys.add_suffix(capture)
    g.add(keys)
    error = Gtk.Label(wrap=True, xalign=0)
    error.add_css_class("error")
    actions = W.group(page)
    actions.add(error)

    def finish():
        if not name_row.get_text().strip() or not command_row.get_text().strip():
            error.set_label("Enter a name and a command.")
            return
        if not state["binding"]:
            error.set_label("Set a key combination.")
            return
        save(name_row.get_text().strip(), command_row.get_text().strip(), state["binding"])
        dialog.close()
    done = W.text_button("Save", finish, suggested=True)
    done.set_halign(Gtk.Align.END)
    actions.add(done)

    def start_capture(*_):
        state["capturing"] = True
        keys.set_subtitle("Press the keys… (Escape cancels)")
        capture.grab_focus()

    def key_pressed(controller, keyval, keycode, modifiers):
        if not state["capturing"]:
            return False
        mods = modifiers & Gtk.accelerator_get_default_mod_mask()
        if keyval == Gdk.KEY_Escape and not mods:
            state["capturing"] = False
            keys.set_subtitle(catalog.accelerator_label(state["binding"]))
            return True
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L,
                      Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
            return True  # wait for the key that goes with the modifiers
        if not mods and keyval not in range(Gdk.KEY_F1, Gdk.KEY_F35 + 1):
            keys.set_subtitle("Add Ctrl, Alt or Super (single keys only for F1–F35)")
            return True
        state["binding"] = Gtk.accelerator_name(Gdk.keyval_to_lower(keyval), mods)
        state["capturing"] = False
        keys.set_subtitle(catalog.accelerator_label(state["binding"]))
        return True

    # Capture phase: see the keys before the focused button turns Enter or
    # Space into a click.
    controller = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    controller.connect("key-pressed", key_pressed)
    dialog.add_controller(controller)
    capture.connect("clicked", start_capture)
    view.set_content(page)
    dialog.set_child(view)
    dialog.present(ctx.window)


# -- Sharing ------------------------------------------------------------------------------

def sharing_page(ctx):
    page = W.page("sharing")
    host = system.Hostname()
    g = W.group(page, "Device name", "How this computer appears on the network and to Bluetooth devices.")
    if host.available:
        name = Adw.EntryRow(title="Name", show_apply_button=True)
        name.set_text(host.pretty)
        name.connect("apply", lambda r: r.get_text().strip() and host.set_name(
            r.get_text().strip(), lambda e: ctx.toast(f"Could not rename: {e}" if e else "Device name changed")))
        g.add(name)
    else:
        g.add(W.plain_row("The device name cannot be changed here", "systemd-hostnamed is not running."))
    rdp = system.RemoteDesktop()
    remote = W.group(page, "Remote Desktop", "Lets someone with the user name and password below see and "
                                             "control this desktop with an RDP client.")
    if not rdp.available:
        remote.add(W.plain_row("Remote Desktop is not installed"))
        return page
    status = rdp.status()
    switch = Adw.SwitchRow(title="Remote Desktop", active=status["rdp"],
                           subtitle=f"Port {status['port']}" if status["port"] else None)
    switch.connect("notify::active", lambda r, _: r.get_active() != rdp.status()["rdp"] and rdp.set_enabled(
        r.get_active(), lambda e: ctx.toast(f"Remote Desktop: {e}" if e else
                                            "Remote Desktop " + ("on" if r.get_active() else "off"))))
    remote.add(switch)
    W.button_row(remote, "Set the user name and password…", lambda: W.form(
        ctx.window, "Remote Desktop sign-in", "Used only for remote connections, not your login password.",
        [("user", "User name", GLib.get_user_name(), "text"), ("password", "Password", "", "password")], "Save",
        lambda v: rdp.set_credentials(v["user"].strip(), v["password"], lambda e: ctx.toast(
            f"Could not save: {e}" if e else "Remote Desktop sign-in saved")),
        lambda v: None if v["user"].strip() and len(v["password"]) >= 8 else "Enter a user name and a password of "
                                                                          "at least 8 characters."),
        "dialog-password-symbolic")
    return page
