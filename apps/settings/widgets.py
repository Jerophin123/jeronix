# SPDX-License-Identifier: GPL-3.0-or-later
"""Building blocks for JERONIX Settings pages.

Every GSettings row is created through settings(schema, key...), which
returns None when the schema or a key is missing (GLib aborts the process on
an unknown key). Rows for missing keys are simply not added, so a setting
that a system lacks disappears instead of crashing the app.

The (schema, key) pairs used by the pages are always written as two string
literals in a row, so tests/unit/test_settings.py can find and check them.
"""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from jeronix_common import shell  # noqa: E402

from . import catalog  # noqa: E402

# Keeps Gio.Settings objects alive for as long as the app runs (bindings
# and signal handlers need them).
_ALIVE = []


def settings(schema_id, *keys):
    """Gio.Settings for schema_id if it is installed and has every key, else None."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(schema_id, True) if source else None
    if schema is None or not all(schema.has_key(k) for k in keys):
        return None
    s = Gio.Settings.new_full(schema, None, None)
    _ALIVE.append(s)
    return s


def relocatable(schema_id, path, *keys):
    """Gio.Settings for a relocatable schema at path, or None."""
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(schema_id, True) if source else None
    if schema is None or not all(schema.has_key(k) for k in keys):
        return None
    s = Gio.Settings.new_full(schema, None, path)
    _ALIVE.append(s)
    return s


def extension_settings(uuid, schema_id, *keys):
    """Gio.Settings of a JERONIX extension's own schema, or None."""
    s = shell.extension_settings(uuid, schema_id)
    if s is None or not all(s.props.settings_schema.has_key(k) for k in keys):
        return None
    _ALIVE.append(s)
    return s


def _key_type(s, key):
    return s.props.settings_schema.get_key(key).get_value_type().dup_string()


# -- pages and groups ---------------------------------------------------------------------

def page(page_id):
    p = catalog.page(page_id)
    return Adw.PreferencesPage(title=p.title, icon_name=p.icon)


def group(page, title=None, description=None):
    g = Adw.PreferencesGroup()
    if title:
        g.set_title(title)
    if description:
        g.set_description(description)
    page.add(g)
    return g


class DynamicGroup:
    """A preferences group whose rows are rebuilt (device and network lists)."""

    def __init__(self, page, title=None, description=None):
        self.group = group(page, title, description)
        self._rows = []

    def clear(self):
        for row in self._rows:
            self.group.remove(row)
        self._rows = []

    def add(self, row):
        self.group.add(row)
        self._rows.append(row)
        return row

    def note(self, title, subtitle=None):
        return self.add(plain_row(title, subtitle))


def debounced(callback, delay=300):
    """A function that runs callback once, delay ms after the last call."""
    state = {"id": 0}

    def run():
        state["id"] = 0
        callback()
        return GLib.SOURCE_REMOVE

    def queue(*_):
        if state["id"]:
            GLib.source_remove(state["id"])
        state["id"] = GLib.timeout_add(delay, run)
    return queue


def latest(send):
    """For sliders that drive a service: queue(value) sends value now, or,
    while a send is still in flight, remembers only the newest value and
    sends it as soon as the previous one is done. Changes apply while the
    slider moves, never pile up, and the last position always wins.
    send(value, done) must call done() when the service has answered."""
    state = {"busy": False, "pending": None}

    def done(*_):
        state["busy"] = False
        if state["pending"] is not None:
            value, state["pending"] = state["pending"], None
            queue(value)

    def queue(value):
        if state["busy"]:
            state["pending"] = value
            return
        state["busy"] = True
        try:
            send(value, done)
        except Exception:  # a failed send must not block later ones
            state["busy"] = False
            raise
    return queue


class Follow:
    """Two-way link between a slider and a value that also changes elsewhere
    (keys, the Control Center, other apps). Moving the slider calls
    store(value); outside changes move the slider with show(value), except
    while the person is dragging it, so it never jumps under the pointer.
    The slider shows the final outside value once they stop."""

    QUIET_US = 400_000  # how long after the last drag step outside values wait

    def __init__(self, scale, store):
        self.scale = scale
        self._store = store
        self._loading = False
        self._last_local = 0
        self._pending = None
        self._timer = 0
        scale.connect("value-changed", self._changed)
        scale.connect("destroy", lambda *_: self._cancel())

    def _changed(self, scale):
        if self._loading:
            return
        self._last_local = GLib.get_monotonic_time()
        self._store(scale.get_value())

    def show(self, value):
        quiet = GLib.get_monotonic_time() - self._last_local
        if quiet < self.QUIET_US:
            self._pending = value
            if not self._timer:
                self._timer = GLib.timeout_add(max(1, (self.QUIET_US - quiet) // 1000), self._flush)
            return
        self._set(value)

    def _flush(self):
        self._timer = 0
        if self._pending is not None:
            value, self._pending = self._pending, None
            self.show(value)
        return GLib.SOURCE_REMOVE

    def _set(self, value):
        if abs(self.scale.get_value() - value) < 1e-4:
            return
        self._loading = True
        self.scale.set_value(value)
        self._loading = False

    def _cancel(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0


def plain_row(title, subtitle=None, activatable=False):
    """An Adw.ActionRow showing text as is. Rows parse Pango markup by
    default, so names from devices and networks ("Tom & Jerry") need this."""
    row = Adw.ActionRow(title=title, use_markup=False, activatable=activatable)
    if subtitle:
        row.set_subtitle(subtitle)
    return row


def flat_button(icon, tooltip, callback):
    b = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    b.add_css_class("flat")
    b.connect("clicked", lambda *_: callback())
    return b


def text_button(label, callback, suggested=False, destructive=False):
    b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if suggested:
        b.add_css_class("suggested-action")
    if destructive:
        b.add_css_class("destructive-action")
    b.connect("clicked", lambda *_: callback())
    return b


def app_icon(gicon, size=32):
    """An app's icon, or a generic one when the icon theme lacks it (never
    GTK's broken-image placeholder)."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if gicon is None or (isinstance(gicon, Gio.ThemedIcon) and not theme.has_gicon(gicon)):
        image = Gtk.Image(icon_name="application-x-executable")
    else:
        image = Gtk.Image.new_from_gicon(gicon)
    image.set_pixel_size(size)
    return image


# -- rows bound to GSettings ----------------------------------------------------------------

def switch(g, s, key, title, subtitle=None, invert=False):
    """A switch bound to a boolean key; None (and nothing added) if s is None."""
    if s is None:
        return None
    row = Adw.SwitchRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    flags = Gio.SettingsBindFlags.INVERT_BOOLEAN if invert else Gio.SettingsBindFlags.DEFAULT
    s.bind(key, row, "active", flags)
    g.add(row)
    return row


def choice(g, s, key, title, choices, subtitle=None, label=None):
    """A drop-down for a string/enum key (choices: [(value, label)]) or a
    number key (choices: values, shown with label(value))."""
    if s is None:
        return None
    kind = _key_type(s, key)
    getter, setter = {
        "s": (s.get_string, s.set_string), "u": (s.get_uint, s.set_uint), "i": (s.get_int, s.set_int),
        "d": (s.get_double, s.set_double),
    }[kind]
    if kind == "s":
        values = [v for v, _ in choices]
        labels = [text for _, text in choices]
    else:
        values = list(choices)
        labels = [label(v) if label else str(v) for v in values]
    current = getter(key)
    if current not in values:  # keep a value set elsewhere selectable
        values.append(current)
        labels.append(label(current) if label and kind != "s" else str(current))
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
    if subtitle:
        row.set_subtitle(subtitle)
    state = {"loading": False}

    def load(*_):
        value = getter(key)
        if value in values:
            state["loading"] = True
            row.set_selected(values.index(value))
            state["loading"] = False

    def store(r, _):
        index = r.get_selected()
        if not state["loading"] and 0 <= index < len(values) and getter(key) != values[index]:
            setter(key, values[index])

    load()
    row.connect("notify::selected", store)
    s.connect(f"changed::{key}", load)
    g.add(row)
    return row


def scale(g, s, key, title, lower, upper, step, subtitle=None, marks=()):
    """A slider row for a double/uint/int key."""
    if s is None:
        return None
    kind = _key_type(s, key)
    getter, setter = {
        "d": (s.get_double, s.set_double), "u": (s.get_uint, s.set_uint), "i": (s.get_int, s.set_int),
    }[kind]
    row = Adw.ActionRow(title=title)
    if subtitle:
        row.set_subtitle(subtitle)
    widget = slider(lower, upper, step)
    widget.set_value(getter(key))

    def store(value):
        value = value if kind == "d" else int(round(value))
        if getter(key) != value:
            setter(key, value)

    # Applied as the slider moves; changes made elsewhere move it too.
    follow = Follow(widget, store)
    s.connect(f"changed::{key}", lambda *_: follow.show(getter(key)))
    row.add_suffix(with_end_labels(widget, marks))
    g.add(row)
    return row


def slider(lower, upper, step):
    widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
    widget.set_hexpand(True)
    widget.set_size_request(200, -1)
    widget.set_draw_value(False)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def with_end_labels(widget, marks):
    """The slider between small labels for its two ends ("Slow ... Fast"),
    which, unlike marks, never spill out of the row."""
    if not marks:
        return widget
    box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
    ends = sorted(marks)
    for text, position in ((ends[0][1], 0), (ends[-1][1], 1)):
        label = Gtk.Label(label=text)
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        if position == 0:
            box.append(label)
            box.append(widget)
        else:
            box.append(label)
    return box


# -- other rows ---------------------------------------------------------------------------

def info(g, title, value, icon=None):
    """A read-only row: title and a value on the right."""
    row = Adw.ActionRow(title=title)
    if icon:
        row.add_prefix(Gtk.Image(icon_name=icon))
    # Short values stay on one line; long ones wrap at about 40 characters.
    label = Gtk.Label(label=value, selectable=True, wrap=True, xalign=1, valign=Gtk.Align.CENTER,
                      width_chars=min(len(value), 40), max_width_chars=40)
    label.add_css_class("dim-label")
    row.add_suffix(label)
    g.add(row)
    return row


def link(g, title, callback, subtitle=None, icon=None):
    """A row that opens something (a page, an app, a dialog) when activated."""
    row = Adw.ActionRow(title=title, activatable=True)
    if subtitle:
        row.set_subtitle(subtitle)
    if icon:
        row.add_prefix(Gtk.Image(icon_name=icon))
    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
    row.connect("activated", lambda *_: callback())
    g.add(row)
    return row


def button_row(g, title, callback, icon=None):
    row = Adw.ButtonRow(title=title)
    if icon:
        row.set_start_icon_name(icon)
    row.connect("activated", lambda *_: callback())
    g.add(row)
    return row


def key_label(keys):
    label = Gtk.Label(label=keys, valign=Gtk.Align.CENTER)
    label.add_css_class("jeronix-key")
    return label


def extension_switch(g, title, subtitle, uuid):
    row = Adw.SwitchRow(title=title, subtitle=subtitle)
    installed = bool(shell.extension_info(uuid))
    row.set_sensitive(installed)
    if not installed:
        row.set_subtitle("Not installed")
    row.set_active(shell.is_active(uuid))
    row.connect("notify::active", lambda r, _: shell.set_enabled(uuid, r.get_active()))
    g.add(row)
    return row


# -- dialogs ------------------------------------------------------------------------------

def confirm(window, heading, body, action, callback, destructive=False):
    """Asks before doing something; callback() runs on confirmation."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", action)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive
                                   else Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel" if destructive else "ok")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda d, response: response == "ok" and callback())
    dialog.present(window)
    return dialog


def form(window, heading, body, fields, action, callback, validate=None):
    """A dialog with entry rows. fields: [(key, title, initial, kind)] with
    kind 'text' or 'password'. callback(values) runs on confirmation;
    validate(values) returns an error message (shown, blocks) or None."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    box.add_css_class("boxed-list")
    entries = {}
    for key, title, initial, kind in fields:
        row = Adw.PasswordEntryRow(title=title) if kind == "password" else Adw.EntryRow(title=title)
        row.set_text(initial or "")
        box.append(row)
        entries[key] = row
    error = Gtk.Label(wrap=True, xalign=0, margin_top=8)
    error.add_css_class("error")
    error.set_visible(False)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content.append(box)
    content.append(error)
    dialog.set_extra_child(content)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", action)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")
    values = lambda: {k: e.get_text() for k, e in entries.items()}  # noqa: E731

    def check(*_):
        problem = validate(values()) if validate else None
        error.set_label(problem or "")
        error.set_visible(bool(problem))
        dialog.set_response_enabled("ok", problem is None)

    for e in entries.values():
        e.connect("changed", check)
    check()
    dialog.connect("response", lambda d, response: response == "ok" and callback(values()))
    dialog.present(window)
    return dialog


def choose_file(window, title, callback, images=False, patterns=()):
    """Opens a file chooser; callback(path) with the chosen file."""
    dialog = Gtk.FileDialog(title=title)
    if images or patterns:
        flt = Gtk.FileFilter(name="Pictures" if images else "Supported files")
        if images:
            flt.add_pixbuf_formats()
        for pattern in patterns:
            flt.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dialog.set_filters(filters)

    def done(d, result):
        try:
            file = d.open_finish(result)
        except GLib.Error:
            return  # cancelled
        if file and file.get_path():
            callback(file.get_path())
    dialog.open(window, None, done)


def pick(window, heading, items, callback, search_placeholder="Search"):
    """A searchable list dialog. items: [(value, title, subtitle)];
    callback(value) when one is chosen."""
    dialog = Adw.Dialog(title=heading, content_width=420, content_height=520)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8, margin_bottom=12,
                  margin_start=12, margin_end=12)
    entry = Gtk.SearchEntry(placeholder_text=search_placeholder)
    box.append(entry)
    listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    rows = []
    for value, title, subtitle in items:
        row = plain_row(title, subtitle, activatable=True)
        row.value, row.haystack = value, f"{title} {subtitle or ''}".lower()
        row.connect("activated", lambda r: (dialog.close(), callback(r.value)))
        listbox.append(row)
        rows.append(row)

    def filter_rows(*_):
        words = entry.get_text().lower().split()
        for row in rows:
            row.set_visible(all(w in row.haystack for w in words))
    entry.connect("search-changed", filter_rows)
    scroller = Gtk.ScrolledWindow(child=listbox, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    box.append(scroller)
    view.set_content(box)
    dialog.set_child(view)
    dialog.present(window)
    entry.grab_focus()
    return dialog


def launch(desktop_id):
    """Starts an application by desktop ID; returns success."""
    app = shell.desktop_app_info(desktop_id)
    if not app:
        return False
    try:
        return app.launch([], None)
    except GLib.Error:
        return False
