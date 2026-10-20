# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound, Displays and Printers pages of JERONIX Settings."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import displays_model as DM  # noqa: E402
from . import system  # noqa: E402
from . import widgets as W  # noqa: E402


# -- Sound -----------------------------------------------------------------------------------

def sound_page(ctx):
    mixer = system.Mixer(lambda: None)  # the page sets on_devices
    if mixer.available:
        return _live_sound_page(mixer)
    return _wpctl_sound_page()


SOUND_KINDS = (("sinks", "Output", "Speakers and headphones", "Volume", "Mute"),
               ("sources", "Input", "Microphone", "Input level", "Mute the microphone"))


def _live_sound_page(mixer):
    """Sound through libgvc: sliders, mute and devices follow every change
    as it happens, from here or anywhere else (keys, the Control Center)."""
    page = W.page("sound")
    page.jeronix_mixer = mixer  # lives as long as the page
    above = W.settings("org.gnome.desktop.sound", "allow-volume-above-100-percent")
    groups = {kind: W.DynamicGroup(page, title) for kind, title, *_ in SOUND_KINDS}
    # Signal handlers on streams, removed whenever the rows are rebuilt.
    handlers = []
    scales = []
    # The mixer keeps retrying a missing sound server; after a while, say so.
    waited = {"long": False}

    def connect(obj, signal, callback):
        handlers.append((obj, obj.connect(signal, callback)))

    def upper():
        return mixer.max_amplified / mixer.max_normal if above and above.get_boolean(
            "allow-volume-above-100-percent") else 1.0

    def rebuild():
        for obj, handler in handlers:
            obj.disconnect(handler)
        handlers.clear()
        scales.clear()
        for kind, _, device_title, level_title, mute_title in SOUND_KINDS:
            g = groups[kind]
            g.clear()
            if mixer.failed or (waited["long"] and not mixer.ready):
                g.note("Sound is not available", "PipeWire or PulseAudio is not running.")
                continue
            if not mixer.ready:
                g.note("Connecting to the sound server…")
                continue
            devices = mixer.devices(kind)
            stream = mixer.default(kind)
            if not devices or stream is None:
                g.note("No device", "No speakers or headphones are connected." if kind == "sinks"
                       else "No microphone is connected.")
                continue
            ids = [d.get_id() for d in devices]
            combo = Adw.ComboRow(title=device_title,
                                 model=Gtk.StringList.new([d.get_description() or d.get_name() for d in devices]))
            if stream.get_id() in ids:
                combo.set_selected(ids.index(stream.get_id()))
            combo.connect("notify::selected", lambda r, _, k=kind, items=devices: _choose(mixer, k, items, r))
            g.add(combo)
            level = g.add(_level_row(mixer, stream, level_title, upper() if kind == "sinks" else 1.0, connect))
            if kind == "sinks":
                scales.append(level.jeronix_scale)
            g.add(_mute_row(stream, mute_title, connect))

    if above:
        def rescale(*_):
            for scale in scales:
                scale.set_range(0, upper())
        above.connect("changed::allow-volume-above-100-percent", rescale)
    # Device lists change in bursts (a headset brings an output and an input).
    mixer.on_devices = W.debounced(rebuild, 150)
    rebuild()

    def give_up():
        waited["long"] = True
        if not mixer.ready:
            rebuild()
        return GLib.SOURCE_REMOVE
    GLib.timeout_add_seconds(5, give_up)
    _alerts_group(page)
    return page


def _choose(mixer, kind, devices, row):
    index = row.get_selected()
    current = mixer.default(kind)
    if 0 <= index < len(devices) and (current is None or devices[index].get_id() != current.get_id()):
        mixer.set_default(kind, devices[index])


def _level_row(mixer, stream, title, upper, connect):
    row = Adw.ActionRow(title=title)
    scale = W.slider(0, upper, 0.01)
    scale.set_value(mixer.level(stream))

    def store(value):
        mixer.set_level(stream, value)
        # As in GNOME Shell: raising a muted volume unmutes it.
        if value > 0 and stream.get_is_muted():
            stream.change_is_muted(False)

    follow = W.Follow(scale, store)
    connect(stream, "notify::volume", lambda *_: follow.show(mixer.level(stream)))
    row.add_suffix(scale)
    row.jeronix_scale = scale
    return row


def _mute_row(stream, title, connect):
    row = Adw.SwitchRow(title=title, active=stream.get_is_muted())
    state = {"loading": False}

    def load(*_):
        if row.get_active() != stream.get_is_muted():
            state["loading"] = True
            row.set_active(stream.get_is_muted())
            state["loading"] = False

    row.connect("notify::active", lambda r, _: state["loading"] or r.get_active() == stream.get_is_muted()
                or stream.change_is_muted(r.get_active()))
    connect(stream, "notify::is-muted", load)
    return row


def _alerts_group(page):
    alerts = W.group(page, "Alerts")
    W.switch(alerts, W.settings("org.gnome.desktop.sound", "event-sounds"),
             "event-sounds", "Alert sounds")
    W.switch(alerts, W.settings("org.gnome.desktop.sound", "allow-volume-above-100-percent"),
             "allow-volume-above-100-percent", "Allow volume above 100%", "Can distort the sound")


def _wpctl_sound_page():
    """Sound through wpctl, when libgvc is missing: sliders apply as they
    move and follow outside changes by polling."""
    page = W.page("sound")
    volume = system.Volume()
    devices = volume.devices()
    watched = []
    for title, node, kind, default in (("Output", volume.SINK, "sinks", "default_sink"),
                                       ("Input", volume.SOURCE, "sources", "default_source")):
        g = W.group(page, title)
        available = devices[kind]
        if available:
            names = [d["description"] for d in available]
            row = Adw.ComboRow(title="Speakers and headphones" if kind == "sinks" else "Microphone",
                               model=Gtk.StringList.new(names))
            current = [d["name"] for d in available].index(devices[default]) \
                if devices[default] in [d["name"] for d in available] else 0
            row.set_selected(current)
            row.connect("notify::selected", lambda r, _, items=available: volume.set_default(
                items[r.get_selected()]["id"]))
            g.add(row)
        level = volume.get(node)
        if level is None:
            g.add(W.plain_row("No device", "No sound device, or WirePlumber is not running."))
            continue
        value, muted = level
        row = Adw.ActionRow(title="Volume" if node == volume.SINK else "Input level")
        scale = W.slider(0, 1, 0.01)
        scale.set_value(min(value, 1.0))
        send = W.latest(lambda v, done, n=node: volume.set(n, v, done))
        follow = W.Follow(scale, send)
        row.add_suffix(scale)
        g.add(row)
        mute = Adw.SwitchRow(title="Mute" if node == volume.SINK else "Mute the microphone", active=muted)
        mute_state = {"loading": False}
        mute.connect("notify::active", lambda r, _, n=node, st=mute_state: st["loading"]
                     or volume.set_muted(n, r.get_active()))
        g.add(mute)
        watched.append((node, follow, mute, mute_state))

    def poll():
        # wpctl has no change notifications; follow outside changes while shown.
        if page.get_mapped():
            for node, follow, mute, mute_state in watched:
                level = volume.get(node)
                if level is not None:
                    follow.show(min(level[0], 1.0))
                    if mute.get_active() != level[1]:
                        mute_state["loading"] = True
                        mute.set_active(level[1])
                        mute_state["loading"] = False
        return GLib.SOURCE_CONTINUE

    if watched:
        source = GLib.timeout_add(1000, poll)
        page.connect("destroy", lambda *_: GLib.source_remove(source))
    _alerts_group(page)
    return page


# -- Displays ---------------------------------------------------------------------------------

def displays_page(ctx):
    page = W.page("displays")
    service = system.Displays()
    brightness = system.ShellBrightness()
    groups = []
    state = {"serial": None, "monitors": [], "layout": DM.LAYOUT_LOGICAL, "dirty": False,
             "night_light": service.night_light_supported()}
    # The brightness slider shown now (rebuilt with the page), and whether
    # it is adjustable, to rebuild only when that changes.
    shown = {"follow": None, "adjustable": None}

    def mark_dirty():
        state["dirty"] = True

    def load(*_):
        """Reads the current configuration from Mutter and redraws."""
        current = service.state()
        state["dirty"] = False
        if current is None:
            state["monitors"] = None
        else:
            state["serial"], state["monitors"], state["layout"] = current
        render()

    def render():
        """Rebuilds every group, in order (a page can only append groups)."""
        for g in groups:
            page.remove(g)
        groups.clear()
        groups.append(_brightness_group(page, brightness, shown))
        monitors = state["monitors"]
        if monitors is None:
            g = W.group(page)
            g.add(W.plain_row("Display settings are not available", "Mutter's display service did not answer."))
            groups.append(g)
        else:
            for index, m in enumerate(monitors):
                groups.append(_monitor_group(page, m, monitors, index, len(monitors) > 1,
                                             lambda: (mark_dirty(), sync_buttons()), render))
            actions = W.group(page)
            buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END)
            buttons.append(W.text_button("Reset", load))
            buttons.append(W.text_button("Apply", apply, suggested=True))
            actions.add(buttons)
            groups.append(actions)
            state["buttons"] = buttons
            sync_buttons()
        groups.append(_night_light_group(page, state["night_light"]))

    def sync_buttons():
        buttons = state.get("buttons")
        if buttons is not None:
            buttons.set_sensitive(state["dirty"])

    def apply():
        def done(error):
            if error:
                ctx.toast(f"Could not apply: {error}")
            else:
                ctx.toast("Keep or revert the change in the dialog GNOME shows")
                load()
        service.apply(state["serial"], state["monitors"], state["layout"], done)

    # Changes made elsewhere (a monitor plugged in, GNOME's revert) are shown,
    # unless there are edits not applied yet.
    service.watch(W.debounced(lambda: None if state["dirty"] else load()))

    def brightness_changed():
        # Keys, the Control Center or Quick Settings changed it, or a screen
        # with adjustable brightness came or went.
        if brightness.adjustable != shown["adjustable"]:
            render()
        elif shown["follow"] is not None:
            shown["follow"].show(brightness.level)
    brightness.watch(brightness_changed)
    load()
    return page


def _brightness_group(page, brightness, shown):
    g = W.group(page, "Brightness")
    shown["adjustable"] = brightness.adjustable
    shown["follow"] = None
    if not brightness.running:
        g.add(W.plain_row("Brightness control is off",
                          "Turn on JERONIX Quick Settings (jeronix-quick-settings) in Extensions."))
    elif not brightness.adjustable:
        g.add(W.plain_row("Not adjustable here",
                          "This screen has no adjustable brightness. Use the buttons on the monitor."))
    else:
        row = Adw.ActionRow(title="Screen brightness")
        row.add_prefix(Gtk.Image(icon_name="display-brightness-symbolic"))
        scale = W.slider(0, 1, 0.01)
        scale.set_value(brightness.level)
        shown["follow"] = W.Follow(scale, W.latest(brightness.set_level))
        row.add_suffix(scale)
        g.add(row)
    return g


def _night_light_group(page, supported=True):
    """Night Light lives with the displays, as on macOS. Its controls are
    shown only where the displays can show it: elsewhere (most virtual
    machines) they would change nothing."""
    color = W.settings("org.gnome.settings-daemon.plugins.color", "night-light-enabled")
    night = W.group(page, "Night Light", "Warmer colors in the evening are easier on the eyes.")
    if color is None:
        night.add(W.plain_row("Night Light is not available"))
        return night
    if not supported:
        night.add(W.plain_row("Not supported by this display",
                              "The graphics driver can't change the screen's colors (common in virtual machines)."))
        return night
    W.switch(night, color, "night-light-enabled", "Night Light")
    W.switch(night, W.settings("org.gnome.settings-daemon.plugins.color", "night-light-schedule-automatic"),
             "night-light-schedule-automatic", "Sunset to sunrise", "Off: from 20:00 to 06:00")
    W.scale(night, W.settings("org.gnome.settings-daemon.plugins.color", "night-light-temperature"),
            "night-light-temperature", "Color temperature", 1700, 4700, 100,
            marks=((1700, "Warmer"), (4700, "Less warm")))
    return night


def _monitor_group(page, m, monitors, index, several, changed, redraw):
    title = m.name + (" (built-in)" if m.builtin else "")
    g = W.group(page, title)
    enabled = [x for x in monitors if x.enabled]
    if several:
        use = Adw.SwitchRow(title="Use this display", active=m.enabled)
        use.set_sensitive(not (m.enabled and len(enabled) == 1))

        def toggle(row, _):
            m.enabled = row.get_active()
            if m.enabled and m.mode_id is None and m.modes:
                m.mode_id = next((md.id for md in m.modes if md.preferred), m.modes[0].id)
            if m.primary and not m.enabled:
                m.primary = False
                next(x for x in monitors if x.enabled).primary = True
            changed()
            redraw()
        use.connect("notify::active", toggle)
        g.add(use)
    if not m.enabled or m.mode is None:
        return g
    if several:
        primary = Adw.SwitchRow(title="Primary display", subtitle="The taskbar and new windows appear here",
                                active=m.primary)
        primary.set_sensitive(not m.primary)

        def make_primary(row, _):
            if row.get_active():
                for x in monitors:
                    x.primary = x is m
                changed()
                redraw()
        primary.connect("notify::active", make_primary)
        g.add(primary)

    resolutions = m.resolutions()
    resolution = Adw.ComboRow(title="Resolution", model=Gtk.StringList.new([f"{w} × {h}" for w, h in resolutions]))
    resolution.set_selected(resolutions.index(m.mode.resolution))
    rates = m.rates(m.mode.resolution)
    rate = Adw.ComboRow(title="Refresh rate", model=Gtk.StringList.new([DM.rate_label(md) for md in rates]))
    rate.set_selected(rates.index(m.mode))
    scales = list(m.mode.scales)
    scale = Adw.ComboRow(title="Scale", model=Gtk.StringList.new([DM.scale_label(s) for s in scales]))
    scale.set_selected(scales.index(m.scale) if m.scale in scales else 0)
    rotations = list(DM.ROTATIONS)
    rotation = Adw.ComboRow(title="Orientation", model=Gtk.StringList.new([label for _, label in rotations]))
    rotation.set_selected(next((i for i, (t, _) in enumerate(rotations) if t == m.transform), 0))

    def pick_resolution(row, _):
        chosen = resolutions[row.get_selected()]
        best = m.rates(chosen)[0]
        if best.resolution != m.mode.resolution:
            m.mode_id = best.id
            m.scale = DM.nearest_scale(best, m.scale)
            changed()
            redraw()

    def pick_rate(row, _):
        chosen = rates[row.get_selected()]
        if chosen.id != m.mode_id:
            m.mode_id = chosen.id
            m.scale = DM.nearest_scale(chosen, m.scale)
            changed()

    def pick_scale(row, _):
        if scales[row.get_selected()] != m.scale:
            m.scale = scales[row.get_selected()]
            changed()

    def pick_rotation(row, _):
        transform = rotations[row.get_selected()][0]
        if transform != m.transform:
            m.transform = transform
            changed()

    resolution.connect("notify::selected", pick_resolution)
    rate.connect("notify::selected", pick_rate)
    scale.connect("notify::selected", pick_scale)
    rotation.connect("notify::selected", pick_rotation)
    for row in (resolution, rate, scale, rotation):
        g.add(row)
    if several and len(enabled) > 1:
        arrange = W.plain_row("Arrangement", "Displays are placed side by side in this order, left to right")
        position = [x for x in monitors if x.enabled].index(m)

        def move(delta):
            i = monitors.index(m)
            j = i + delta
            while 0 <= j < len(monitors) and not monitors[j].enabled:
                j += delta
            if 0 <= j < len(monitors):
                monitors[i], monitors[j] = monitors[j], monitors[i]
                changed()
                redraw()
        left = W.flat_button("go-previous-symbolic", "Move left", lambda: move(-1))
        right = W.flat_button("go-next-symbolic", "Move right", lambda: move(1))
        left.set_sensitive(position > 0)
        right.set_sensitive(position < len(enabled) - 1)
        arrange.add_suffix(left)
        arrange.add_suffix(right)
        g.add(arrange)
    return g


# -- Printers -----------------------------------------------------------------------------

def printers_page(ctx):
    page = W.page("printers")
    printers = system.Printers()
    if not printers.available:
        W.group(page).add(W.plain_row("Printing is not installed", "The CUPS printing system is missing."))
        return page
    listed = W.DynamicGroup(page, "Printers")
    listed.group.set_header_suffix(W.flat_button("view-refresh-symbolic", "Refresh", lambda: refresh()))
    add = W.DynamicGroup(page, "Add a printer", "Printers on the network that support driverless printing "
                                                "usually appear on their own. Others can be added here.")
    search = W.button_row(add.group, "Look for printers", lambda: discover(), "system-search-symbolic")

    def done(what):
        def callback(error):
            ctx.toast(f"{what} failed: {error}" if error else f"{what}: done")
            refresh()
        return callback

    def refresh():
        listed.clear()
        found = printers.printers()
        if not found:
            listed.note("No printers", "Connect a printer, or look for one below.")
        for p in found:
            status = ("Default · " if p["default"] else "") + (p["state"] if p["enabled"] else "Paused")
            row = W.plain_row(p["name"], status)
            row.add_prefix(Gtk.Image(icon_name="printer-symbolic"))
            menu = Gtk.Box(spacing=4)
            if not p["default"]:
                menu.append(W.text_button("Make default", lambda n=p["name"]: printers.set_default(
                    n, done("Default printer"))))
            menu.append(W.flat_button("document-print-symbolic", "Print a test page",
                                      lambda n=p["name"]: printers.test_page(n, done("Test page"))))
            menu.append(W.flat_button("media-playback-pause-symbolic" if p["enabled"] else "media-playback-start-symbolic",
                                      "Pause printing" if p["enabled"] else "Resume printing",
                                      lambda n=p["name"], on=not p["enabled"]: printers.set_enabled(
                                          n, on, done("Printer"))))
            menu.append(W.flat_button("edit-clear-all-symbolic", "Cancel all jobs",
                                      lambda n=p["name"]: printers.cancel_jobs(n, done("Cancel jobs"))))
            menu.append(W.flat_button("user-trash-symbolic", "Remove this printer", lambda n=p["name"]: W.confirm(
                ctx.window, f"Remove {n}?", "Its queue and settings are deleted.", "Remove",
                lambda: printers.remove(n, done("Remove printer")), True)))
            menu.set_valign(Gtk.Align.CENTER)
            row.add_suffix(menu)
            listed.add(row)

    def discover():
        add.clear()
        search.set_sensitive(False)
        add.add(W.plain_row("Looking for printers…", "This can take up to a minute."))

        def found(devices):
            search.set_sensitive(True)
            add.clear()
            if not devices:
                add.note("No printers found")
            for d in devices:
                row = W.plain_row(d["uri"], "Network" if d["kind"] == "network" else "Connected to this computer")
                row.add_suffix(W.text_button("Add", lambda dev=d: W.form(
                    ctx.window, "Add printer", f"Driverless printing (IPP Everywhere) for {dev['uri']}.",
                    [("name", "Name", "Printer", "text")], "Add",
                    lambda values: printers.add(values["name"], dev["uri"], done("Add printer")),
                    lambda values: None if values["name"].strip() else "Enter a name.")))
                add.add(row)
        printers.discover(found)

    refresh()
    return page
