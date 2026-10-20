# SPDX-License-Identifier: GPL-3.0-or-later
"""Wi-Fi, Bluetooth and Network pages of JERONIX Settings."""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import catalog, system  # noqa: E402
from . import widgets as W  # noqa: E402

try:
    gi.require_version("NMA4", "1.0")
    from gi.repository import NMA4  # NetworkManager's own Wi-Fi dialogs (enterprise, hidden networks)
except (ImportError, ValueError):
    NMA4 = None


# -- Wi-Fi ------------------------------------------------------------------------------

def wifi_page(ctx):
    page = W.page("wifi")
    net = system.Network()
    rfkill = system.Rfkill()
    if not net.available or not net.wifi_device():
        W.group(page).add(W.plain_row("No Wi-Fi adapter",
                                      "This computer has no Wi-Fi hardware, or NetworkManager is not running."))
        _airplane_group(page, rfkill)
        return page

    main = W.group(page)
    toggle = Adw.SwitchRow(title="Wi-Fi")
    main.add(toggle)
    current = W.plain_row("Not connected")
    current.add_prefix(Gtk.Image(icon_name="network-wireless-symbolic"))
    forget = W.flat_button("user-trash-symbolic", "Forget this network", lambda: forget_current())
    disconnect = W.text_button("Disconnect", net.disconnect_wifi)
    current.add_suffix(forget)
    current.add_suffix(disconnect)
    main.add(current)
    _airplane_group(page, rfkill)

    networks = W.DynamicGroup(page, "Networks")
    networks.group.set_header_suffix(W.flat_button("view-refresh-symbolic", "Search again", net.scan))
    other = W.group(page)
    if NMA4:
        W.button_row(other, "Connect to a hidden network…", lambda: _nma_dialog(ctx, net, None), "list-add-symbolic")
    state = {"loading": False}

    def forget_current():
        ssid = net.active_ssid()
        if ssid:
            W.confirm(ctx.window, f"Forget {ssid}?", "Its password is removed and it is not joined automatically "
                      "any more.", "Forget", lambda: (net.forget(ssid), ctx.toast(f"Forgot {ssid}")), True)

    def done(error, ssid):
        if error:
            ctx.toast(f"Could not connect to {ssid}: {error}")

    def choose(network):
        if network["enterprise"] or network["wep"]:
            if NMA4:
                _nma_dialog(ctx, net, network)
            else:
                ctx.toast(f"{network['ssid']} needs enterprise sign-in, which this system cannot set up here.")
            return
        if network["secure"] and not net.saved_connection(network["ssid"]):
            _ask_password(ctx, network, lambda password: net.connect_wifi(
                network, password, lambda e: done(e, network["ssid"])))
        else:
            net.connect_wifi(network, None, lambda e: done(e, network["ssid"]))

    def refresh():
        state["loading"] = True
        toggle.set_active(net.wifi_enabled)
        toggle.set_sensitive(net.wifi_hardware_enabled)
        state["loading"] = False
        active = net.active_ssid() if net.wifi_enabled else None
        current.set_title(active or ("Not connected" if net.wifi_enabled else "Wi-Fi is off"))
        current.set_subtitle("Connected" if active else "")
        disconnect.set_visible(bool(active))
        forget.set_visible(bool(active))
        networks.clear()
        networks.group.set_visible(net.wifi_enabled)
        other.set_visible(net.wifi_enabled)
        if not net.wifi_enabled:
            return
        visible = [n for n in net.access_points() if n["ssid"] != active]
        if not visible:
            networks.note("Searching for networks…")
        for network in visible:
            row = W.plain_row(network["ssid"], "Saved" if net.saved_connection(network["ssid"]) else None,
                              activatable=True)
            row.add_prefix(Gtk.Image(icon_name=catalog.signal_icon(network["strength"])))
            if network["secure"]:
                row.add_suffix(Gtk.Image(icon_name="channel-secure-symbolic", tooltip_text="Secured"))
            row.connect("activated", lambda r, n=network: choose(n))
            networks.add(row)

    def switched(row, _):
        if not state["loading"]:
            net.set_wifi_enabled(row.get_active(), lambda e: e and ctx.toast(f"Could not switch Wi-Fi: {e}"))

    toggle.connect("notify::active", switched)
    net.watch(W.debounced(refresh))
    refresh()
    net.scan()
    return page


def _airplane_group(page, rfkill):
    if not rfkill.has_airplane_mode:
        return
    g = W.group(page)
    row = Adw.SwitchRow(title="Airplane Mode", subtitle="Turns off Wi-Fi, Bluetooth and mobile broadband")
    state = {"loading": False}

    def load():
        state["loading"] = True
        row.set_active(rfkill.airplane_mode)
        state["loading"] = False

    row.connect("notify::active", lambda r, _: state["loading"] or rfkill.set_airplane_mode(r.get_active()))
    rfkill.watch(load)
    load()
    g.add(row)


def _ask_password(ctx, network, connect):
    dialog = Adw.AlertDialog(heading=f"Connect to {network['ssid']}", body="Enter the network password.")
    entry = Gtk.PasswordEntry(show_peek_icon=True, activates_default=True)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("connect", "Connect")
    dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("connect")
    dialog.set_close_response("cancel")
    dialog.set_response_enabled("connect", False)
    # WPA passwords are 8 to 63 characters.
    entry.connect("changed", lambda e: dialog.set_response_enabled("connect", 8 <= len(e.get_text()) <= 63))
    dialog.connect("response", lambda d, response: response == "connect" and connect(entry.get_text()))
    dialog.present(ctx.window)


def _nma_dialog(ctx, net, network):
    """NetworkManager's own dialog: enterprise (802.1X), WEP and hidden networks."""
    device = net.wifi_device()
    if network is None:
        dialog = NMA4.WifiDialog.new_for_other(net.client)
    else:
        dialog = NMA4.WifiDialog.new(net.client, None, device, network["ap"], False)
    if dialog is None:
        ctx.toast("NetworkManager could not open its Wi-Fi dialog.")
        return
    dialog.set_transient_for(ctx.window)
    dialog.set_modal(True)

    def response(d, response_id):
        if response_id == Gtk.ResponseType.OK:
            connection, chosen_device, ap = d.get_connection()
            if connection is not None:
                net.add_and_activate(connection, chosen_device or device, ap.get_path() if ap else None,
                                     lambda e: e and ctx.toast(f"Could not connect: {e}"))
        d.destroy()
    dialog.connect("response", response)
    dialog.present()


# -- Bluetooth ----------------------------------------------------------------------------

class PairingUI:
    """Dialogs for the pairing agent (system.BluetoothAgent)."""

    def __init__(self, ctx):
        self._ctx = ctx
        self._dialog = None

    def _show(self, dialog):
        self.cancel()
        self._dialog = dialog
        dialog.present(self._ctx.window)

    def confirm(self, name, text, answer):
        dialog = Adw.AlertDialog(heading=f"Pair with {name}?", body=text)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("pair", "Pair")
        dialog.set_response_appearance("pair", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda d, r: answer(r == "pair"))
        self._show(dialog)

    def ask_code(self, name, numeric, answer):
        dialog = Adw.AlertDialog(heading=f"Pair with {name}",
                                 body="Enter the passkey shown on the device." if numeric
                                 else "Enter the PIN code of the device (often 0000 or 1234).")
        entry = Gtk.Entry(activates_default=True, input_purpose=Gtk.InputPurpose.DIGITS if numeric
                          else Gtk.InputPurpose.FREE_FORM)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("pair", "Pair")
        dialog.set_response_appearance("pair", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("pair")
        dialog.set_close_response("cancel")
        dialog.set_response_enabled("pair", False)

        def valid(text):
            if numeric:
                return text.isdigit() and int(text) <= 999999
            return 1 <= len(text) <= 16

        entry.connect("changed", lambda e: dialog.set_response_enabled("pair", valid(e.get_text())))
        dialog.connect("response", lambda d, r: answer(entry.get_text() if r == "pair" else None))
        self._show(dialog)

    def show_code(self, name, code):
        dialog = Adw.AlertDialog(heading=f"Pairing with {name}", body=f"Type {code} on the device, then press Enter.")
        dialog.add_response("close", "Close")
        self._show(dialog)

    def cancel(self):
        if self._dialog is not None:
            self._dialog.force_close()
            self._dialog = None


def bluetooth_page(ctx):
    page = W.page("bluetooth")
    rfkill = system.Rfkill()
    bt = system.Bluetooth()
    main = W.group(page)
    if not rfkill.has_bluetooth or not bt.adapter():
        main.add(W.plain_row("No Bluetooth adapter",
                             "This computer has no Bluetooth hardware, or it is switched off in firmware."))
        return page
    toggle = Adw.SwitchRow(title="Bluetooth")
    main.add(toggle)
    mine = W.DynamicGroup(page, "My devices")
    nearby = W.DynamicGroup(page, "Nearby devices", "Make the device discoverable (usually by holding its "
                                                    "Bluetooth button), then choose it here.")
    state = {"loading": False, "pairing": None}
    agent = system.BluetoothAgent(bt.bus, PairingUI(ctx), bt.name_of) if bt.bus else None

    def after(error, what):
        if error:
            ctx.toast(f"{what} failed: {error}")
        refresh()

    def pair(device):
        state["pairing"] = device["path"]
        refresh()

        def done(error):
            state["pairing"] = None
            after(error, f"Pairing with {device['name']}")
            if not error:
                ctx.toast(f"{device['name']} is paired")
        bt.pair(device, done)

    def refresh():
        state["loading"] = True
        toggle.set_active(rfkill.bluetooth_on)
        state["loading"] = False
        mine.clear()
        nearby.clear()
        on = rfkill.bluetooth_on
        mine.group.set_visible(on)
        nearby.group.set_visible(on)
        if not on:
            return
        devices = bt.devices()
        paired = [d for d in devices if d["paired"]]
        if not paired:
            mine.note("No paired devices")
        for device in paired:
            row = W.plain_row(device["name"], "Connected" if device["connected"] else "Not connected")
            row.add_prefix(Gtk.Image(icon_name=device["icon"]))
            if device["connected"]:
                row.add_suffix(W.text_button("Disconnect", lambda d=device: bt.disconnect(
                    d, lambda e: after(e, "Disconnecting"))))
            else:
                row.add_suffix(W.text_button("Connect", lambda d=device: bt.connect(
                    d, lambda e: after(e, "Connecting"))))
            row.add_suffix(W.flat_button("user-trash-symbolic", "Forget this device", lambda d=device: W.confirm(
                ctx.window, f"Forget {d['name']}?", "You will need to pair it again to use it.", "Forget",
                lambda: bt.forget(d, lambda e: after(e, "Forgetting")), True)))
            mine.add(row)
        others = [d for d in devices if not d["paired"]]
        if not others:
            nearby.note("Looking for devices…")
        for device in others:
            row = W.plain_row(device["name"])
            row.add_prefix(Gtk.Image(icon_name=device["icon"]))
            if state["pairing"] == device["path"]:
                row.add_suffix(Adw.Spinner())
            else:
                button = W.text_button("Pair", lambda d=device: pair(d))
                button.set_sensitive(state["pairing"] is None)
                row.add_suffix(button)
            nearby.add(row)

    def switched(row, _):
        if not state["loading"]:
            error = rfkill.set_bluetooth(row.get_active())
            if error:
                ctx.toast(f"Could not switch Bluetooth: {error}")

    # Look for devices and answer pairing requests only while the page is shown.
    def shown(*_):
        if agent:
            error = agent.register()
            if error:
                ctx.toast(f"Pairing is not available: {error}")
        bt.set_discovering(True)
        bt.watch(W.debounced(refresh, 500))
        refresh()

    def hidden(*_):
        bt.unwatch()
        bt.set_discovering(False)
        if agent:
            agent.unregister()

    page.connect("map", shown)
    page.connect("unmap", hidden)
    toggle.connect("notify::active", switched)
    rfkill.watch(W.debounced(refresh))
    refresh()
    return page


# -- Network -------------------------------------------------------------------------------

def network_page(ctx):
    page = W.page("network")
    net = system.Network()
    wired = W.DynamicGroup(page, "Wired")
    vpn = W.DynamicGroup(page, "VPN")
    vpn.group.set_header_suffix(W.flat_button("list-add-symbolic", "Add a VPN from a file", lambda: W.choose_file(
        ctx.window, "Choose an OpenVPN (.ovpn) or WireGuard (.conf) file",
        lambda path: system.Network.import_vpn(path, lambda e: ctx.toast(e or "VPN added")),
        patterns=("*.ovpn", "*.conf"))))

    def refresh():
        wired.clear()
        vpn.clear()
        if not net.available:
            wired.note("NetworkManager is not running")
            vpn.group.set_visible(False)
            return
        devices = net.wired()
        if not devices:
            wired.note("No wired network adapter")
        for d in devices:
            row = W.plain_row(d["name"], ("Connected · " + ", ".join(d["addresses"])) if d["connected"]
                              else "Cable unplugged")
            row.add_prefix(Gtk.Image(icon_name="network-wired-symbolic"))
            if d["connection"] is not None:
                row.add_suffix(W.flat_button("emblem-system-symbolic", "Details and IP settings",
                                             lambda dev=d: _wired_dialog(ctx, net, dev)))
            wired.add(row)
        vpn.group.set_visible(True)
        vpns = net.vpns()
        if not vpns:
            vpn.note("No VPN connections", "Add one from an OpenVPN or WireGuard file with +.")
        for v in vpns:
            row = Adw.SwitchRow(title=v["name"], use_markup=False,
                                subtitle="WireGuard" if v["kind"] == "wireguard" else "VPN")
            row.set_active(bool(v["active"]))
            row.connect("notify::active", lambda r, _, item=v: bool(item["active"]) != r.get_active() and
                        net.toggle_vpn(item, lambda e: e and ctx.toast(f"VPN: {e}")))
            row.add_suffix(W.flat_button("user-trash-symbolic", "Remove this VPN", lambda item=v: W.confirm(
                ctx.window, f"Remove {item['name']}?", "Its settings are deleted from this computer.", "Remove",
                lambda: net.delete(item["connection"], lambda e: e and ctx.toast(e)), True)))
            vpn.add(row)

    net.watch(W.debounced(refresh))
    refresh()

    proxy = W.settings("org.gnome.system.proxy", "mode", "autoconfig-url", "ignore-hosts")
    g = W.group(page, "Proxy")
    W.choice(g, W.settings("org.gnome.system.proxy", "mode"),
             "mode", "Proxy", [("none", "Off"), ("auto", "Automatic (configuration URL)"), ("manual", "Manual")])
    if proxy:
        url = Adw.EntryRow(title="Configuration URL", show_apply_button=True)
        url.set_text(proxy.get_string("autoconfig-url"))
        url.connect("apply", lambda r: proxy.set_string("autoconfig-url", r.get_text().strip()))
        g.add(url)
        rows = {"auto": [url], "manual": []}
        for scheme, title in (("http", "HTTP proxy"), ("https", "HTTPS proxy")):
            s = W.settings(f"org.gnome.system.proxy.{scheme}", "host", "port")
            if s is None:
                continue
            host = Adw.EntryRow(title=f"{title} host", show_apply_button=True)
            host.set_text(s.get_string("host"))
            host.connect("apply", lambda r, st=s: st.set_string("host", r.get_text().strip()))
            port = Adw.SpinRow.new_with_range(0, 65535, 1)
            port.set_title(f"{title} port")
            s.bind("port", port, "value", Gio.SettingsBindFlags.DEFAULT)
            g.add(host)
            g.add(port)
            rows["manual"] += [host, port]
        ignore = Adw.EntryRow(title="Ignore hosts (comma-separated)", show_apply_button=True)
        ignore.set_text(", ".join(proxy.get_strv("ignore-hosts")))
        ignore.connect("apply", lambda r: proxy.set_strv(
            "ignore-hosts", [h.strip() for h in r.get_text().split(",") if h.strip()]))
        g.add(ignore)
        rows["manual"].append(ignore)

        def sync_mode(*_):
            mode = proxy.get_string("mode")
            for kind, widgets in rows.items():
                for w in widgets:
                    w.set_visible(mode == kind)
        proxy.connect("changed::mode", sync_mode)
        sync_mode()
    W.link(W.group(page), "Wi-Fi", lambda: ctx.show("wifi"), icon="network-wireless-symbolic")
    return page


def _wired_dialog(ctx, net, device):
    """Connection details, and IPv4 settings: automatic or manual."""
    current = net.ipv4(device["connection"])
    dialog = Adw.Dialog(title=device["name"], content_width=440)
    view = Adw.ToolbarView()
    view.add_top_bar(Adw.HeaderBar())
    page = Adw.PreferencesPage()
    facts = W.group(page, "Details")
    W.info(facts, "Hardware address", device["mac"] or "unknown")
    W.info(facts, "IPv4 address", ", ".join(device["addresses"]) or "none")
    W.info(facts, "Gateway", device["gateway"] or "none")
    W.info(facts, "DNS", ", ".join(device["dns"]) or "none")
    ipv4 = W.group(page, "IPv4")
    methods = [("auto", "Automatic (DHCP)"), ("manual", "Manual")]
    method = Adw.ComboRow(title="Method", model=Gtk.StringList.new([m for _, m in methods]))
    method.set_selected(1 if current["method"] == "manual" else 0)
    address = Adw.EntryRow(title="Address (e.g. 192.168.1.20/24)")
    address.set_text(current["address"])
    gateway = Adw.EntryRow(title="Gateway")
    gateway.set_text(current["gateway"])
    dns = Adw.EntryRow(title="DNS servers (comma-separated; empty: automatic)")
    dns.set_text(current["dns"])
    for row in (method, address, gateway, dns):
        ipv4.add(row)
    error = Gtk.Label(wrap=True, xalign=0)
    error.add_css_class("error")
    actions = W.group(page)
    actions.add(error)
    save = W.text_button("Save and reconnect", lambda: apply(), suggested=True)
    save.set_halign(Gtk.Align.END)
    actions.add(save)

    def sync(*_):
        manual = method.get_selected() == 1
        address.set_visible(manual)
        gateway.set_visible(manual)
    method.connect("notify::selected", sync)
    sync()

    def apply():
        manual = method.get_selected() == 1
        try:
            addr = catalog.parse_ipv4(address.get_text()) if manual else None
            gw = catalog.parse_ipv4_list(gateway.get_text()) if manual else []
            if len(gw) > 1:
                raise ValueError("Enter one gateway.")
            servers = catalog.parse_ipv4_list(dns.get_text())
        except ValueError as e:
            error.set_label(str(e))
            return
        error.set_label("")
        net.set_ipv4(device["connection"], "manual" if manual else "auto", addr, gw[0] if gw else None, servers,
                     lambda e: ctx.toast(f"Could not save: {e}" if e else "Network settings saved"))
        dialog.close()

    view.set_content(page)
    dialog.set_child(view)
    dialog.present(ctx.window)
