# SPDX-License-Identifier: GPL-3.0-or-later
"""System services behind JERONIX Settings, all through stable public
interfaces: NetworkManager (libnm), Mutter's DisplayConfig, gsd-rfkill,
BlueZ, UPower, power-profiles-daemon, AccountsService, timedated and
hostnamed over D-Bus, and the CUPS, WirePlumber, PipeWire, nmcli and
grdctl command-line tools.

Every service reports itself unavailable instead of raising, so a missing
daemon hides a control rather than breaking the app. Actions that need
permission go through polkit: D-Bus calls carry the
ALLOW_INTERACTIVE_AUTHORIZATION flag, so GNOME asks for a password, and run
asynchronously with a long timeout, so the window never freezes while it
waits. Passwords are never put on a command line.
"""

import os
import shutil
import subprocess

import gi
from gi.repository import Gio, GLib

try:
    gi.require_version("NM", "1.0")
    from gi.repository import NM
except (ImportError, ValueError):
    NM = None

from . import catalog, displays_model

INTERACTIVE = Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION
# Long enough for a person to answer a password prompt.
AUTH_TIMEOUT = 5 * 60 * 1000


def _warn(what, error):
    # A missing service is normal (no Bluetooth, a desktop without battery),
    # so details are printed only on request.
    if os.environ.get("JERONIX_DEBUG"):
        print(f"JERONIX Settings: {what}: {error}", flush=True)


def _bus(bus_type):
    try:
        return Gio.bus_get_sync(bus_type, None)
    except GLib.Error as e:
        _warn("bus unavailable", e.message)
        return None


def call_async(bus_type, name, path, iface, method, params=None, done=None, reply_type=None, interactive=False):
    """Calls a D-Bus method; done(result or None, error message or None)."""
    bus = _bus(bus_type)
    if bus is None:
        if done:
            done(None, "D-Bus is not available")
        return

    def finish(connection, result, *_):
        try:
            value = connection.call_finish(result)
            error = None
        except GLib.Error as e:
            value, error = None, e.message
        if done:
            done(value, error)

    bus.call(name, path, iface, method, params, reply_type,
             INTERACTIVE if interactive else Gio.DBusCallFlags.NONE,
             AUTH_TIMEOUT if interactive else 30000, None, finish)


def run_async(argv, done=None, stdin_text=None, c_locale=True):
    """Runs a command; done(ok, stdout, stderr). Text on stdin, if any, is
    how secrets are passed (never on the command line)."""
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    if stdin_text is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    launcher = Gio.SubprocessLauncher.new(flags)
    if c_locale:
        launcher.setenv("LC_ALL", "C", True)
    try:
        process = launcher.spawnv(argv)
    except GLib.Error as e:
        if done:
            done(False, "", e.message)
        return

    def finish(proc, result, *_):
        try:
            _, out, err = proc.communicate_utf8_finish(result)
            ok = proc.get_successful()
        except GLib.Error as e:
            ok, out, err = False, "", e.message
        if done:
            done(ok, out or "", err or "")

    process.communicate_utf8_async(stdin_text, None, finish)


def run_sync(argv, stdin_text=None, timeout=5):
    """(ok, stdout) of a quick command in the C locale."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=stdin_text,
                           env={**os.environ, "LC_ALL": "C"})
        return r.returncode == 0, r.stdout
    except (OSError, subprocess.SubprocessError) as e:
        _warn(argv[0], e)
        return False, ""


class DBusProperties:
    """Property access on one D-Bus object (fast local calls)."""

    def __init__(self, bus_type, name, path, iface):
        self.bus_type, self.name, self.path, self.iface = bus_type, name, path, iface
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(bus_type, Gio.DBusProxyFlags.NONE, None,
                                                        name, path, iface, None)
        except GLib.Error as e:
            _warn(f"{name} unavailable", e.message)
            self.proxy = None

    @property
    def available(self):
        return bool(self.proxy and self.proxy.get_name_owner())

    def get(self, prop, default=None):
        if not self.available:
            return default
        value = self.proxy.get_cached_property(prop)
        return default if value is None else value.unpack()

    def set(self, prop, variant):
        """Sets prop; returns an error message or None."""
        if not self.available:
            return "service not available"
        try:
            self.proxy.call_sync("org.freedesktop.DBus.Properties.Set",
                                 GLib.Variant("(ssv)", (self.iface, prop, variant)),
                                 Gio.DBusCallFlags.NONE, 10000, None)
            return None
        except GLib.Error as e:
            return e.message

    def call(self, method, params=None, done=None, interactive=False, reply_type=None):
        call_async(self.bus_type, self.name, self.path, self.iface, method, params, done, reply_type, interactive)

    def watch(self, callback):
        if self.proxy:
            self.proxy.connect("g-properties-changed", lambda *_: callback())


# -- radios and network -------------------------------------------------------------------

class Rfkill(DBusProperties):
    """Bluetooth and airplane mode switches of gsd-rfkill."""

    def __init__(self):
        super().__init__(Gio.BusType.SESSION, "org.gnome.SettingsDaemon.Rfkill", "/org/gnome/SettingsDaemon/Rfkill",
                         "org.gnome.SettingsDaemon.Rfkill")

    @property
    def has_bluetooth(self):
        return self.get("BluetoothHasAirplaneMode", False) is True

    @property
    def bluetooth_on(self):
        return self.get("BluetoothAirplaneMode", True) is False

    def set_bluetooth(self, on):
        return self.set("BluetoothAirplaneMode", GLib.Variant("b", not on))

    @property
    def has_airplane_mode(self):
        return self.get("HasAirplaneMode", False) is True

    @property
    def airplane_mode(self):
        return self.get("AirplaneMode", False) is True

    def set_airplane_mode(self, on):
        return self.set("AirplaneMode", GLib.Variant("b", on))


def _ssid_text(ssid_bytes):
    if ssid_bytes is None:
        return None
    data = ssid_bytes.get_data()
    return NM.utils_ssid_to_utf8(data) if data else None


def _finish(method, done):
    """A libnm async callback that calls done(error or None)."""
    def callback(source, result, *_):
        try:
            getattr(source, method)(result)
            error = None
        except GLib.Error as e:
            error = e.message
        if done:
            done(error)
    return callback


class Network:
    """NetworkManager: Wi-Fi, wired and VPN connections."""

    def __init__(self):
        self.client = None
        if NM is None:
            return
        try:
            self.client = NM.Client.new(None)
        except GLib.Error as e:
            _warn("NetworkManager unavailable", e.message)

    @property
    def available(self):
        return self.client is not None and self.client.get_nm_running()

    def watch(self, callback):
        if not self.client:
            return
        for signal in ("notify::wireless-enabled", "notify::active-connections", "device-added", "device-removed",
                       "connection-added", "connection-removed"):
            self.client.connect(signal, lambda *_: callback())
        device = self.wifi_device()
        if device:
            for signal in ("access-point-added", "access-point-removed", "state-changed"):
                device.connect(signal, lambda *_: callback())

    def devices(self, kind):
        if not self.available:
            return []
        return [d for d in self.client.get_devices() if d.get_device_type() == kind]

    def wifi_device(self):
        devices = self.devices(NM.DeviceType.WIFI) if NM else []
        return devices[0] if devices else None

    @property
    def wifi_enabled(self):
        return bool(self.available and self.client.wireless_get_enabled())

    @property
    def wifi_hardware_enabled(self):
        return bool(self.available and self.client.wireless_hardware_get_enabled())

    def set_wifi_enabled(self, enabled, done=None):
        self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                      GLib.Variant("b", enabled), -1, None, _finish("dbus_set_property_finish", done))

    def active_ssid(self):
        device = self.wifi_device()
        ap = device.get_active_access_point() if device else None
        return _ssid_text(ap.get_ssid()) if ap else None

    def access_points(self):
        """[{ssid, strength, secure, wep, enterprise, sae_only, path, ap}]."""
        device = self.wifi_device()
        if not device:
            return []
        points = []
        for ap in device.get_access_points():
            points.append(dict(catalog.ap_security(int(ap.get_flags()), int(ap.get_wpa_flags()),
                                                   int(ap.get_rsn_flags())),
                               ssid=_ssid_text(ap.get_ssid()), strength=int(ap.get_strength()),
                               path=ap.get_path(), ap=ap))
        return catalog.wifi_networks(points)

    def scan(self):
        device = self.wifi_device()
        if device:
            device.request_scan_async(None, _finish("request_scan_finish", None))

    def saved_connection(self, ssid):
        if not self.available:
            return None
        for connection in self.client.get_connections():
            wireless = connection.get_setting_wireless()
            if wireless and _ssid_text(wireless.get_ssid()) == ssid:
                return connection
        return None

    def connect_wifi(self, network, password=None, done=None):
        """Connects to a WPA/WPA3-personal or open network. done(error or None)."""
        device = self.wifi_device()
        saved = self.saved_connection(network["ssid"])
        if saved and password is None:
            self.client.activate_connection_async(saved, device, None, None,
                                                  _finish("activate_connection_finish", done))
            return
        connection = NM.SimpleConnection.new()
        setting = NM.SettingConnection.new()
        setting.set_property(NM.SETTING_CONNECTION_ID, network["ssid"])
        setting.set_property(NM.SETTING_CONNECTION_UUID, NM.utils_uuid_generate())
        setting.set_property(NM.SETTING_CONNECTION_TYPE, "802-11-wireless")
        connection.add_setting(setting)
        wireless = NM.SettingWireless.new()
        wireless.set_property(NM.SETTING_WIRELESS_SSID, GLib.Bytes.new(network["ssid"].encode("utf-8")))
        wireless.set_property(NM.SETTING_WIRELESS_MODE, "infrastructure")
        connection.add_setting(wireless)
        if network["secure"]:
            security = NM.SettingWirelessSecurity.new()
            security.set_property(NM.SETTING_WIRELESS_SECURITY_KEY_MGMT, "sae" if network["sae_only"] else "wpa-psk")
            security.set_property(NM.SETTING_WIRELESS_SECURITY_PSK, password or "")
            connection.add_setting(security)
        if saved:  # a new password for a saved network replaces it
            saved.delete_async(None, None)
        self.client.add_and_activate_connection_async(connection, device, network["path"], None,
                                                      _finish("add_and_activate_connection_finish", done))

    def add_and_activate(self, connection, device, specific_object, done=None):
        """Activates a connection built by NetworkManager's own dialog."""
        self.client.add_and_activate_connection_async(connection, device, specific_object, None,
                                                      _finish("add_and_activate_connection_finish", done))

    def disconnect_wifi(self):
        device = self.wifi_device()
        if device:
            device.disconnect_async(None, None)

    def forget(self, ssid):
        saved = self.saved_connection(ssid)
        if saved:
            saved.delete_async(None, None)

    # -- wired and VPN --

    def wired(self):
        """[{device, name, connected, addresses, gateway, dns, mac, connection}] for Ethernet devices."""
        if not NM:
            return []
        result = []
        for device in self.devices(NM.DeviceType.ETHERNET):
            config = device.get_ip4_config()
            active = device.get_active_connection()
            result.append({
                "device": device, "name": device.get_iface(),
                "connected": device.get_state() == NM.DeviceState.ACTIVATED,
                "addresses": [f"{a.get_address()}/{a.get_prefix()}" for a in config.get_addresses()] if config else [],
                "gateway": config.get_gateway() if config else None,
                "dns": list(config.get_nameservers()) if config else [],
                "mac": device.get_hw_address(),
                "connection": active.get_connection() if active else None,
            })
        return result

    def ipv4(self, connection):
        """{method, address, gateway, dns} of a connection's IPv4 setting."""
        s = connection.get_setting_ip4_config() if connection else None
        if s is None:
            return {"method": "auto", "address": "", "gateway": "", "dns": ""}
        address = s.get_address(0) if s.get_num_addresses() else None
        return {"method": s.get_method() or "auto",
                "address": f"{address.get_address()}/{address.get_prefix()}" if address else "",
                "gateway": s.get_gateway() or "",
                "dns": ", ".join(s.get_dns(i) for i in range(s.get_num_dns()))}

    def set_ipv4(self, connection, method, address=None, gateway=None, dns=(), done=None):
        """Saves IPv4 settings ('auto' or 'manual') and reapplies the connection."""
        s = connection.get_setting_ip4_config()
        if s is None:
            s = NM.SettingIP4Config.new()
            connection.add_setting(s)
        s.clear_addresses()
        s.clear_dns()
        s.set_property(NM.SETTING_IP_CONFIG_GATEWAY, None)
        s.set_property(NM.SETTING_IP_CONFIG_METHOD, method)
        if method == "manual":
            ip, prefix = address
            s.add_address(NM.IPAddress.new(2, ip, prefix))  # 2 = AF_INET
            if gateway:
                s.set_property(NM.SETTING_IP_CONFIG_GATEWAY, gateway)
        for server in dns:
            s.add_dns(server)
        s.set_property(NM.SETTING_IP_CONFIG_IGNORE_AUTO_DNS, bool(dns) and method == "auto")

        def reactivate(error):
            if error:
                if done:
                    done(error)
                return
            self.client.activate_connection_async(connection, None, None, None,
                                                  _finish("activate_connection_finish", done))
        connection.commit_changes_async(True, None, _finish("commit_changes_finish", reactivate))

    def vpns(self):
        """[{connection, name, kind, active}] for saved VPN and WireGuard connections."""
        if not self.available:
            return []
        active = {a.get_uuid(): a for a in self.client.get_active_connections()}
        return sorted(({"connection": c, "name": c.get_id(), "kind": c.get_connection_type(),
                        "active": active.get(c.get_uuid())}
                       for c in self.client.get_connections() if c.get_connection_type() in ("vpn", "wireguard")),
                      key=lambda v: v["name"].lower())

    def toggle_vpn(self, vpn, done=None):
        if vpn["active"]:
            self.client.deactivate_connection_async(vpn["active"], None, _finish("deactivate_connection_finish", done))
        else:
            self.client.activate_connection_async(vpn["connection"], None, None, None,
                                                  _finish("activate_connection_finish", done))

    def delete(self, connection, done=None):
        connection.delete_async(None, _finish("delete_finish", done))

    @staticmethod
    def import_vpn(path, done):
        """Imports an OpenVPN (.ovpn) or WireGuard (.conf) file with nmcli."""
        kind = catalog.vpn_import_type(path)
        if kind is None:
            done("Choose an OpenVPN (.ovpn) or WireGuard (.conf) file.")
            return
        run_async(["nmcli", "connection", "import", "type", kind, "file", path],
                  lambda ok, out, err: done(None if ok else (err.strip() or "Import failed.")))


# -- Bluetooth -------------------------------------------------------------------------

AGENT_PATH = "/io/jeronix/Settings/BluetoothAgent"
AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
    <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
    <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
    <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="Cancel"/>
  </interface>
</node>
"""


class BluetoothAgent:
    """A BlueZ pairing agent (org.bluez.Agent1) for pairing started here.

    ui must provide: confirm(device_name, text, answer), ask_code(device_name,
    numeric, answer), show_code(device_name, code) and cancel(). answer(value)
    is called once with the reply, or with None to reject.
    """

    REJECTED = "org.bluez.Error.Rejected"

    def __init__(self, bus, ui, device_name):
        self._bus, self._ui, self._device_name = bus, ui, device_name
        self._id = 0
        self._pending = None

    def register(self):
        """Exports the agent and registers it with BlueZ; returns an error or None."""
        info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
        try:
            # register_object_with_closures2 (PyGObject 3.50+) replaces the
            # deprecated register_object override.
            register = getattr(self._bus, "register_object_with_closures2", None) or self._bus.register_object
            self._id = register(AGENT_PATH, info, self.handle, None, None)
            self._bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                                GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")), None,
                                Gio.DBusCallFlags.NONE, 5000, None)
            return None
        except GLib.Error as e:
            self.unregister()
            return e.message

    def unregister(self):
        if self._id:
            try:
                self._bus.call_sync("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent",
                                    GLib.Variant("(o)", (AGENT_PATH,)), None, Gio.DBusCallFlags.NONE, 5000, None)
            except GLib.Error:
                pass  # BlueZ already forgot it (it restarted, or the adapter went away)
            self._bus.unregister_object(self._id)
            self._id = 0

    def handle(self, connection, sender, path, iface, method, params, invocation):
        """Answers BlueZ's agent calls (also called directly by the tests)."""
        args = params.unpack()
        name = self._device_name(args[0]) if args else ""
        if method in ("Release", "Cancel"):
            self._ui.cancel()
            invocation.return_value(None)
        elif method == "AuthorizeService":
            invocation.return_value(None)  # the device was paired from here
        elif method == "RequestConfirmation":
            self._reply(invocation, lambda answer: self._ui.confirm(
                name, f"Does {name} show the passkey {args[1]:06d}?", answer), lambda ok: None)
        elif method == "RequestAuthorization":
            self._reply(invocation, lambda answer: self._ui.confirm(
                name, f"Allow {name} to pair with this computer?", answer), lambda ok: None)
        elif method == "RequestPinCode":
            self._reply(invocation, lambda answer: self._ui.ask_code(name, False, answer),
                        lambda pin: GLib.Variant("(s)", (str(pin),)))
        elif method == "RequestPasskey":
            self._reply(invocation, lambda answer: self._ui.ask_code(name, True, answer),
                        lambda key: GLib.Variant("(u)", (int(key),)))
        elif method == "DisplayPinCode":
            self._ui.show_code(name, args[1])
            invocation.return_value(None)
        elif method == "DisplayPasskey":
            self._ui.show_code(name, f"{args[1]:06d}")
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.NotSupported", method)

    def _reply(self, invocation, ask, to_variant):
        """Asks the UI; replies with to_variant(value), or rejects on None."""
        answered = [False]

        def answer(value):
            if answered[0]:
                return
            answered[0] = True
            if value is None or value is False:
                invocation.return_dbus_error(self.REJECTED, "Rejected by the user")
            else:
                invocation.return_value(to_variant(value))
        ask(answer)


class Bluetooth:
    """BlueZ: adapters, paired and nearby devices, discovery and pairing."""

    def __init__(self):
        self.bus = _bus(Gio.BusType.SYSTEM)
        self._subscription = 0
        self._discovering = None

    def objects(self):
        if not self.bus:
            return {}
        try:
            reply = self.bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                                       None, GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            return {}  # BlueZ not running or no adapter
        return reply.unpack()[0]

    def adapter(self):
        """The first adapter's object path, or None."""
        return next((path for path, ifaces in sorted(self.objects().items()) if "org.bluez.Adapter1" in ifaces), None)

    def devices(self):
        """[{path, adapter, name, icon, paired, connected, rssi}], paired first."""
        devices = []
        for path, interfaces in self.objects().items():
            d = interfaces.get("org.bluez.Device1")
            if not d:
                continue
            name = d.get("Alias") or d.get("Name")
            if not name and not d.get("Paired"):
                continue  # nameless nearby devices are noise
            devices.append({"path": path, "adapter": d.get("Adapter", ""), "name": name or d.get("Address", "Device"),
                            "icon": (d.get("Icon") or "bluetooth") + "-symbolic", "paired": bool(d.get("Paired")),
                            "connected": bool(d.get("Connected")), "rssi": d.get("RSSI")})
        return sorted(devices, key=lambda d: (not d["paired"], not d["connected"], d["name"].lower()))

    def name_of(self, path):
        d = self.objects().get(path, {}).get("org.bluez.Device1", {})
        return d.get("Alias") or d.get("Name") or d.get("Address") or "the device"

    def watch(self, callback):
        """Calls callback whenever BlueZ objects change, until unwatch()."""
        if not self.bus or self._subscription:
            return
        self._subscription = self.bus.signal_subscribe("org.bluez", None, None, None, None,
                                                       Gio.DBusSignalFlags.NONE, lambda *_: callback())

    def unwatch(self):
        if self._subscription:
            self.bus.signal_unsubscribe(self._subscription)
            self._subscription = 0

    def _call(self, path, iface, method, args=None, done=None, timeout=30000):
        def finish(bus, result, *_):
            try:
                bus.call_finish(result)
                error = None
            except GLib.Error as e:
                error = e.message
            if done:
                done(error)
        self.bus.call("org.bluez", path, iface, method, args, None, Gio.DBusCallFlags.NONE, timeout, None, finish)

    def set_discovering(self, on):
        """Starts or stops looking for nearby devices (BlueZ stops it too when this app exits)."""
        adapter = self.adapter() if on else self._discovering
        if not adapter or bool(self._discovering) == on:
            return
        self._discovering = adapter if on else None
        self._call(adapter, "org.bluez.Adapter1", "StartDiscovery" if on else "StopDiscovery",
                   done=lambda e: e and _warn("discovery", e))

    def pair(self, device, done):
        """Pairs, trusts, then connects. done(error or None)."""
        def connected(error):
            done(error)

        def trusted(error):
            if error:
                _warn("trust", error)
            self._call(device["path"], "org.bluez.Device1", "Connect", done=connected)

        def paired(error):
            if error:
                done(error)
                return
            self._call(device["path"], "org.freedesktop.DBus.Properties", "Set",
                       GLib.Variant("(ssv)", ("org.bluez.Device1", "Trusted", GLib.Variant("b", True))), trusted)
        self._call(device["path"], "org.bluez.Device1", "Pair", done=paired, timeout=90000)

    def connect(self, device, done=None):
        self._call(device["path"], "org.bluez.Device1", "Connect", done=done)

    def disconnect(self, device, done=None):
        self._call(device["path"], "org.bluez.Device1", "Disconnect", done=done)

    def forget(self, device, done=None):
        self._call(device["adapter"], "org.bluez.Adapter1", "RemoveDevice",
                   GLib.Variant("(o)", (device["path"],)), done)


# -- sound --------------------------------------------------------------------------

# GNOME Shell's private libraries, where its mixer library (Gvc) lives.
SHELL_LIBDIRS = ("/usr/lib/gnome-shell", "/usr/lib64/gnome-shell", "/usr/lib/x86_64-linux-gnu/gnome-shell",
                 "/usr/lib/aarch64-linux-gnu/gnome-shell")


def load_gvc():
    """GNOME's mixer library (libgvc, what GNOME Shell's volume uses), or
    None. It is installed with GNOME Shell, in the shell's own folder."""
    try:
        gi.require_version("GIRepository", "3.0")
        from gi.repository import GIRepository
        repo = GIRepository.Repository.dup_default()
        for d in SHELL_LIBDIRS:
            if os.path.isdir(d):
                repo.prepend_search_path(d)
                repo.prepend_library_path(d)
        gi.require_version("Gvc", "1.0")
        from gi.repository import Gvc
        return Gvc
    except (ImportError, ValueError, AttributeError, GLib.Error) as e:
        _warn("Gvc mixer unavailable; using wpctl", e)
        return None


class Mixer:
    """Sound through libgvc, connected to PulseAudio/PipeWire like GNOME
    Shell: volumes, mute and devices are live in both directions, changes
    are sent without blocking, and changes made elsewhere are announced.

    on_devices() is called (on the main loop) whenever the device list or
    the default devices change, and once the mixer is ready."""

    def __init__(self, on_devices):
        self.on_devices = on_devices
        self.Gvc = load_gvc()
        self.control = None
        if self.Gvc is None:
            return
        self.control = self.Gvc.MixerControl(name="JERONIX Settings")
        for signal in ("state-changed", "default-sink-changed", "default-source-changed",
                       "output-added", "output-removed", "input-added", "input-removed"):
            self.control.connect(signal, lambda *_: self.on_devices())
        self.control.open()

    @property
    def available(self):
        return self.control is not None

    @property
    def ready(self):
        return bool(self.control) and self.control.get_state() == self.Gvc.MixerControlState.READY

    @property
    def failed(self):
        return bool(self.control) and self.control.get_state() == self.Gvc.MixerControlState.FAILED

    @property
    def max_normal(self):
        return self.control.get_vol_max_norm()

    @property
    def max_amplified(self):
        return self.control.get_vol_max_amplified()

    def devices(self, kind):
        """Hardware streams of kind 'sinks' or 'sources' (no monitors)."""
        streams = self.control.get_sinks() if kind == "sinks" else self.control.get_sources()
        return [s for s in streams if not (s.get_name() or "").endswith(".monitor")]

    def default(self, kind):
        return self.control.get_default_sink() if kind == "sinks" else self.control.get_default_source()

    def set_default(self, kind, stream):
        if kind == "sinks":
            self.control.set_default_sink(stream)
        else:
            self.control.set_default_source(stream)

    def level(self, stream):
        """The stream's volume as a slider value (1.0 is 100%)."""
        return stream.get_volume() / self.max_normal

    def set_level(self, stream, value):
        stream.set_volume(int(round(max(0.0, value) * self.max_normal)))
        stream.push_volume()


class Volume:
    """Volume and devices through WirePlumber (wpctl) and PipeWire (pw-dump),
    used when libgvc is not available."""

    SINK, SOURCE = "@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@"

    def __init__(self):
        self.wpctl = shutil.which("wpctl")
        self.pw_dump = shutil.which("pw-dump")

    def get(self, node):
        """(volume 0..1.5, muted) or None."""
        if not self.wpctl:
            return None
        ok, out = run_sync([self.wpctl, "get-volume", node])
        return catalog.parse_wpctl_volume(out) if ok else None

    def set(self, node, volume, done=None):
        """Sets the volume without blocking; done() when wpctl has finished."""
        if not self.wpctl:
            if done:
                done()
            return
        run_async([self.wpctl, "set-volume", "-l", "1.0", node, f"{max(0.0, min(1.0, volume)):.2f}"],
                  lambda *_: done and done())

    def set_muted(self, node, muted):
        if self.wpctl:
            run_sync([self.wpctl, "set-mute", node, "1" if muted else "0"])

    def devices(self):
        """{sinks, sources, default_sink, default_source} (see catalog.parse_pw_dump)."""
        if not self.pw_dump:
            return catalog.parse_pw_dump("[]")
        ok, out = run_sync([self.pw_dump], timeout=10)
        return catalog.parse_pw_dump(out if ok else "[]")

    def set_default(self, node_id):
        if self.wpctl:
            run_sync([self.wpctl, "set-default", str(node_id)])


class ShellBrightness(DBusProperties):
    """Screen brightness, through the JERONIX service in GNOME Shell
    (desktop/extensions/jeronix-quick-settings/brightness-service.js): the
    same control as the shell's own brightness slider, 0..1."""

    def __init__(self):
        super().__init__(Gio.BusType.SESSION, "org.gnome.Shell", "/io/jeronix/Shell/Brightness",
                         "io.jeronix.Shell.Brightness")

    @property
    def running(self):
        """Whether the JERONIX service answers (the extension is enabled)."""
        return self.get("Available") is not None

    @property
    def adjustable(self):
        """Whether a screen with adjustable brightness is connected."""
        return self.get("Available", False) is True

    @property
    def level(self):
        return self.get("Brightness", 0.0)

    def set_level(self, value, done=None):
        """Sets the brightness without blocking; done() once the shell has it."""
        params = GLib.Variant("(ssv)", ("io.jeronix.Shell.Brightness", "Brightness",
                                        GLib.Variant("d", max(0.0, min(1.0, value)))))
        call_async(self.bus_type, self.name, self.path, "org.freedesktop.DBus.Properties", "Set", params,
                   lambda *_: done and done())


# -- input devices ----------------------------------------------------------------------

UDEV_DATA = "/run/udev/data"


def input_devices_with(prop, udev_data=UDEV_DATA):
    """How many input devices udev tags with prop (e.g. ID_INPUT_TOUCHPAD),
    as GNOME decides what to show; None if udev's database is unreadable."""
    try:
        names = [n for n in os.listdir(udev_data) if n.startswith("c13:")]
    except OSError:
        return None
    count = 0
    for name in names:
        try:
            with open(os.path.join(udev_data, name), encoding="utf-8", errors="replace") as f:
                if f"E:{prop}=1\n" in f.read():
                    count += 1
        except OSError:
            continue
    return count


def virtual_machine():
    """The hypervisor's name ('vmware', 'kvm', ...) or None on real hardware."""
    tool = shutil.which("systemd-detect-virt")
    if not tool:
        return None
    ok, out = run_sync([tool, "--vm"])
    name = out.strip()
    return name if ok and name and name != "none" else None


# -- power ------------------------------------------------------------------------------

class PowerProfiles(DBusProperties):
    """power-profiles-daemon (or tuned-ppd): power-saver, balanced, performance."""

    def __init__(self):
        super().__init__(Gio.BusType.SYSTEM, "org.freedesktop.UPower.PowerProfiles",
                         "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles")
        if not self.available:
            super().__init__(Gio.BusType.SYSTEM, "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
                             "net.hadess.PowerProfiles")

    def profiles(self):
        return [p.get("Profile") for p in self.get("Profiles", []) if p.get("Profile")]

    @property
    def active(self):
        return self.get("ActiveProfile")

    def set_active(self, profile):
        return self.set("ActiveProfile", GLib.Variant("s", profile))


class Battery(DBusProperties):
    """The battery UPower shows in the status area (its display device)."""

    CHARGING, DISCHARGING, FULL = 1, 2, 4

    def __init__(self):
        super().__init__(Gio.BusType.SYSTEM, "org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
                         "org.freedesktop.UPower.Device")

    @property
    def present(self):
        # Type 2 is a battery; desktops report no display device battery.
        return self.get("IsPresent", False) is True and self.get("Type", 0) == 2

    def summary(self):
        percentage = round(self.get("Percentage", 0))
        state = {self.CHARGING: "charging", self.DISCHARGING: "on battery",
                 self.FULL: "fully charged"}.get(self.get("State", 0), "")
        return f"{percentage}%" + (f", {state}" if state else "")


# -- displays ---------------------------------------------------------------------------

class Displays:
    """Mutter's org.gnome.Mutter.DisplayConfig. A persistent change makes
    GNOME show its own "Keep these display settings?" countdown, which
    reverts the change unless it is confirmed."""

    def __init__(self):
        self.bus = _bus(Gio.BusType.SESSION)

    def state(self):
        """(serial, [Monitor], layout_mode) or None."""
        if not self.bus:
            return None
        try:
            reply = self.bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                                       "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
                                       Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as e:
            _warn("display configuration unavailable", e.message)
            return None
        return displays_model.parse_state(reply.unpack())

    def watch(self, callback):
        if self.bus:
            self.bus.signal_subscribe("org.gnome.Mutter.DisplayConfig", "org.gnome.Mutter.DisplayConfig",
                                      "MonitorsChanged", "/org/gnome/Mutter/DisplayConfig", None,
                                      Gio.DBusSignalFlags.NONE, lambda *_: callback())

    def night_light_supported(self):
        """Whether the displays can show Night Light (gamma or color
        transforms); False on most virtual machines. True if unknown, so a
        Mutter without the property keeps the controls."""
        if not self.bus:
            return True
        try:
            reply = self.bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                                       "org.freedesktop.DBus.Properties", "Get",
                                       GLib.Variant("(ss)", ("org.gnome.Mutter.DisplayConfig",
                                                             "NightLightSupported")),
                                       None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error:
            return True
        return bool(reply.unpack()[0])

    @staticmethod
    def variant(arguments):
        serial, method, logical, props = arguments
        return GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (
            serial, method,
            [(x, y, scale, transform, primary, [(c, mode, {}) for c, mode, _ in specs])
             for x, y, scale, transform, primary, specs in logical],
            {"layout-mode": GLib.Variant("u", props["layout-mode"])}))

    def apply(self, serial, monitors, layout_mode, done):
        """Checks the configuration with Mutter, then applies it for good.
        done(error or None)."""
        try:
            check = displays_model.apply_arguments(serial, monitors, layout_mode, displays_model.METHOD_VERIFY)
        except ValueError as e:
            done(str(e))
            return

        def verified(value, error):
            if error:
                done(error)
                return
            final = (check[0], displays_model.METHOD_PERSISTENT, check[2], check[3])
            call_async(Gio.BusType.SESSION, "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                       "org.gnome.Mutter.DisplayConfig", "ApplyMonitorsConfig", self.variant(final),
                       lambda v, e: done(e))
        call_async(Gio.BusType.SESSION, "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                   "org.gnome.Mutter.DisplayConfig", "ApplyMonitorsConfig", self.variant(check), verified)


# -- date and time, device name ------------------------------------------------------------

class TimeDate(DBusProperties):
    """systemd-timedated: time zone, network time, manual time."""

    def __init__(self):
        super().__init__(Gio.BusType.SYSTEM, "org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                         "org.freedesktop.timedate1")

    def set_timezone(self, zone, done):
        self.call("SetTimezone", GLib.Variant("(sb)", (zone, True)), lambda v, e: done(e), interactive=True)

    def set_ntp(self, on, done):
        self.call("SetNTP", GLib.Variant("(bb)", (on, True)), lambda v, e: done(e), interactive=True)

    def set_time(self, unix_usec, done):
        self.call("SetTime", GLib.Variant("(xbb)", (unix_usec, False, True)), lambda v, e: done(e), interactive=True)

    @staticmethod
    def zones():
        ok, out = run_sync(["timedatectl", "list-timezones", "--no-pager"])
        return [z for z in out.split() if z] if ok else []


class Hostname(DBusProperties):
    """systemd-hostnamed: the device name."""

    def __init__(self):
        super().__init__(Gio.BusType.SYSTEM, "org.freedesktop.hostname1", "/org/freedesktop/hostname1",
                         "org.freedesktop.hostname1")

    @property
    def pretty(self):
        return self.get("PrettyHostname") or self.get("StaticHostname") or self.get("Hostname") or GLib.get_host_name()

    def set_name(self, pretty, done):
        """Sets the pretty name and a matching static hostname."""
        def static_done(value, error):
            done(error)

        def pretty_done(value, error):
            if error:
                done(error)
                return
            self.call("SetStaticHostname", GLib.Variant("(sb)", (catalog.static_hostname(pretty), True)),
                      static_done, interactive=True)
        self.call("SetPrettyHostname", GLib.Variant("(sb)", (pretty, True)), pretty_done, interactive=True)


# -- users ------------------------------------------------------------------------------

ACCOUNTS = "org.freedesktop.Accounts"
STANDARD, ADMINISTRATOR = 0, 1


class Accounts:
    """AccountsService over D-Bus. Changes to other users, account types and
    passwords ask for an administrator's password; the own name, picture and
    language need none."""

    def __init__(self):
        self.manager = DBusProperties(Gio.BusType.SYSTEM, ACCOUNTS, "/org/freedesktop/Accounts", ACCOUNTS)

    @property
    def available(self):
        return self.manager.available

    def users(self):
        """[User] of people (not system accounts), the current user first."""
        if not self.available:
            return []
        try:
            paths = self.manager.proxy.call_sync("ListCachedUsers", None, Gio.DBusCallFlags.NONE, 5000,
                                                 None).unpack()[0]
        except GLib.Error as e:
            _warn("users", e.message)
            return []
        me = os.getuid()
        users = [User(p) for p in paths]
        users = [u for u in users if u.available and not u.get("SystemAccount", False)]
        if not any(u.uid == me for u in users):
            own = self.find(me)
            if own:
                users.append(own)
        return sorted(users, key=lambda u: (u.uid != me, u.real_name.lower()))

    def find(self, uid):
        try:
            path = self.manager.proxy.call_sync("FindUserById", GLib.Variant("(x)", (uid,)), Gio.DBusCallFlags.NONE,
                                                5000, None).unpack()[0]
        except GLib.Error:
            return None
        user = User(path)
        return user if user.available else None

    def create(self, name, full_name, account_type, done):
        self.manager.call("CreateUser", GLib.Variant("(ssi)", (name, full_name, account_type)),
                          lambda v, e: done(None if e else v.unpack()[0], e), interactive=True)

    def delete(self, user, remove_files, done):
        self.manager.call("DeleteUser", GLib.Variant("(xb)", (user.uid, remove_files)),
                          lambda v, e: done(e), interactive=True)


def hash_password(password):
    """A SHA-512 crypt hash for AccountsService, made by openssl from stdin."""
    ok, out = run_sync(["openssl", "passwd", "-6", "-stdin"], stdin_text=password + "\n")
    out = out.strip()
    if not ok or not out.startswith("$6$"):
        raise RuntimeError("Could not encrypt the password (is openssl installed?).")
    return out


class User(DBusProperties):
    def __init__(self, path):
        super().__init__(Gio.BusType.SYSTEM, ACCOUNTS, path, "org.freedesktop.Accounts.User")

    @property
    def uid(self):
        return int(self.get("Uid", -1))

    @property
    def user_name(self):
        return self.get("UserName", "")

    @property
    def real_name(self):
        return self.get("RealName") or self.user_name

    @property
    def is_admin(self):
        return self.get("AccountType", STANDARD) == ADMINISTRATOR

    @property
    def icon_file(self):
        path = self.get("IconFile", "")
        return path if path and os.path.isfile(path) else None

    @property
    def is_me(self):
        return self.uid == os.getuid()

    def _set(self, method, signature, value, done, interactive=True):
        self.call(method, GLib.Variant(signature, (value,)), lambda v, e: done(e) if done else None,
                  interactive=interactive)

    def set_real_name(self, name, done=None):
        self._set("SetRealName", "(s)", name, done)

    def set_icon(self, path, done=None):
        self._set("SetIconFile", "(s)", path, done)

    def set_admin(self, admin, done=None):
        self._set("SetAccountType", "(i)", ADMINISTRATOR if admin else STANDARD, done)

    def set_automatic_login(self, on, done=None):
        self._set("SetAutomaticLogin", "(b)", on, done)

    def set_language(self, locale, done=None):
        self._set("SetLanguage", "(s)", locale, done)

    def set_password(self, password, done):
        try:
            hashed = hash_password(password)
        except RuntimeError as e:
            done(str(e))
            return
        self.call("SetPassword", GLib.Variant("(ss)", (hashed, "")), lambda v, e: done(e), interactive=True)


# -- printers --------------------------------------------------------------------------

class Printers:
    """CUPS through its command-line tools (members of the lpadmin group,
    the default for the first Ubuntu user, manage printers without a password)."""

    TEST_PAGE = "/usr/share/cups/data/testprint"

    @property
    def available(self):
        return bool(shutil.which("lpstat"))

    def printers(self):
        ok, out = run_sync(["lpstat", "-p"])
        printers = catalog.parse_lpstat_printers(out) if ok else []
        ok, out = run_sync(["lpstat", "-d"])
        default = catalog.parse_lpstat_default(out) if ok else None
        for p in printers:
            p["default"] = p["name"] == default
        return printers

    @staticmethod
    def _done(done, what):
        return lambda ok, out, err: done(None if ok else (err.strip() or f"{what} failed."))

    def set_default(self, name, done):
        run_async(["lpoptions", "-d", name], self._done(done, "Setting the default printer"))

    def test_page(self, name, done):
        if not os.path.isfile(self.TEST_PAGE):
            done("The CUPS test page is not installed.")
            return
        run_async(["lp", "-d", name, self.TEST_PAGE], self._done(done, "Printing a test page"))

    def cancel_jobs(self, name, done):
        run_async(["cancel", "-a", name], self._done(done, "Cancelling the jobs"))

    def set_enabled(self, name, on, done):
        run_async(["cupsenable" if on else "cupsdisable", name], self._done(done, "Changing the printer"))

    def remove(self, name, done):
        run_async(["lpadmin", "-x", name], self._done(done, "Removing the printer"))

    def discover(self, done):
        """done([{uri, kind}]) after CUPS has looked for devices (takes a while)."""
        run_async(["lpinfo", "-v"], lambda ok, out, err: done(catalog.parse_lpinfo(out) if ok else []))

    def add(self, name, uri, done):
        """Adds a driverless (IPP Everywhere) printer."""
        run_async(["lpadmin", "-p", catalog.printer_name(name), "-E", "-v", uri, "-m", "everywhere"],
                  self._done(done, "Adding the printer"))


# -- remote desktop --------------------------------------------------------------------------

class RemoteDesktop:
    """GNOME Remote Desktop (RDP) through grdctl."""

    @property
    def available(self):
        return bool(shutil.which("grdctl"))

    def status(self):
        ok, out = run_sync(["grdctl", "status"])
        return catalog.parse_grdctl_status(out)

    def set_enabled(self, on, done):
        run_async(["grdctl", "rdp", "enable" if on else "disable"],
                  lambda ok, out, err: done(None if ok else (err.strip() or "Failed.")))

    def set_credentials(self, username, password, done):
        """grdctl reads the password from stdin when it is not an argument."""
        run_async(["grdctl", "rdp", "set-credentials", username],
                  lambda ok, out, err: done(None if ok else (err.strip() or "Failed.")), stdin_text=password + "\n")


def hostname():
    return GLib.get_host_name()
