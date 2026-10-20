# SPDX-License-Identifier: GPL-3.0-or-later
"""JERONIX Settings without a display: the page catalog, search, parsers,
list rules and the display model, and static checks of the page modules
(every page has a builder, every settings key a row binds was checked to
exist first, extension keys are real, the Control Center's module lists
agree). With PyGObject and the GNOME schemas installed, every system key is
also checked against the installed schemas and the Bluetooth agent's
answers are exercised."""

import ast
import importlib.util
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "scripts"))

from settings import catalog  # noqa: E402
from settings import displays_model as DM  # noqa: E402

import jeronix_symbolic  # noqa: E402

SETTINGS_DIR = ROOT / "apps" / "settings"
PAGE_MODULES = sorted(SETTINGS_DIR.glob("pages*.py"))
SCHEMAS = {
    "DOCK_SCHEMA": ROOT / "desktop" / "extensions" / "jeronix-dock" / "schemas"
                   / "org.gnome.shell.extensions.jeronix-dock.gschema.xml",
    "PANEL_SCHEMA": ROOT / "desktop" / "extensions" / "jeronix-panel" / "schemas"
                    / "org.gnome.shell.extensions.jeronix-panel.gschema.xml",
}
ROW_BUILDERS = {"switch", "choice", "scale"}
HAVE_GI = importlib.util.find_spec("gi") is not None

# GetCurrentState of a real VMware session (Ubuntu 26.04, Mutter 50), trimmed.
MUTTER_STATE = (
    1,
    [(("Virtual-1", "unknown", "unknown", "unknown"), [
        ("4096x2160@60.000", 4096, 2160, 60.0, 1.0, [1.0, 1.3333, 2.0, 2.6667, 4.0], {}),
        ("2560x1600@59.987", 2560, 1600, 59.987, 1.0, [1.0, 1.25, 1.3333, 1.6667, 2.0, 2.5, 2.6667],
         {"is-current": True, "is-preferred": True}),
        ("2560x1600@59.972", 2560, 1600, 59.972, 1.0, [1.0, 1.25, 1.3333, 1.6667, 2.0, 2.5, 2.6667], {}),
        ("1920x1080@60.000", 1920, 1080, 60.0, 1.0, [1.0, 1.25, 1.5, 2.0], {}),
    ], {"display-name": "Unknown Display", "is-builtin": False}),
     (("HDMI-1", "DEL", "U2723", "X"), [
         ("1920x1080@60.000", 1920, 1080, 60.0, 1.0, [1.0, 1.25, 1.5, 2.0], {"is-current": True}),
     ], {"display-name": "Dell 27\"", "is-builtin": False})],
    [(0, 0, 1.25, 0, True, [("Virtual-1", "unknown", "unknown", "unknown")], {}),
     (2048, 0, 1.0, 0, False, [("HDMI-1", "DEL", "U2723", "X")], {})],
    {"layout-mode": 1, "supports-changing-layout-mode": True},
)

PW_DUMP = json.dumps([
    {"id": 49, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Device"}}},
    {"id": 58, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Audio/Sink", "node.name": "alsa_output.pci-0000_02_02.0.analog-stereo",
        "node.description": "ES1371 Analog Stereo"}}},
    {"id": 59, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Audio/Source", "node.name": "alsa_input.pci-0000_02_02.0.analog-stereo",
        "node.description": "ES1371 Analog Stereo"}}},
    {"id": 31, "type": "PipeWire:Interface:Metadata", "props": {"metadata.name": "default"}, "metadata": [
        {"subject": 0, "key": "default.audio.sink", "type": "Spa:String:JSON",
         "value": {"name": "alsa_output.pci-0000_02_02.0.analog-stereo"}},
        {"subject": 0, "key": "default.audio.source", "type": "Spa:String:JSON",
         "value": {"name": "alsa_input.pci-0000_02_02.0.analog-stereo"}}]},
])

GRDCTL_STATUS = """Overall:
\tUnit status: inactive
RDP:
\tStatus: disabled
\tPort: 3389
\tAuthentication methods: credentials
"""


def schema_keys(path):
    return {k.get("name") for k in ET.parse(path).getroot().iter("key")}


def is_w_call(node, name):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "W")


def literal_strings(nodes):
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


class CatalogTests(unittest.TestCase):
    def test_pages_are_unique_and_complete(self):
        ids = [p.id for p in catalog.PAGES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(catalog.DEFAULT_PAGE, ids)
        for p in catalog.PAGES:
            with self.subTest(page=p.id):
                self.assertIn(p.color, catalog.COLORS)
                self.assertTrue(p.title)
                self.assertTrue((SETTINGS_DIR / "icons" / f"{p.icon}.svg").is_file(), "the page's icon is shipped")
        groups = [p.group for p in catalog.PAGES]
        self.assertEqual(groups, sorted(groups), "a sidebar group must be contiguous")

    def test_sidebar_colors_are_readable_with_white_icons(self):
        def luminance(hex_color):
            channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for name, color in catalog.COLORS.items():
            with self.subTest(color=name):
                self.assertGreaterEqual(1.05 / (luminance(color) + 0.05), 4.5)

    def test_search(self):
        def ids(query):
            return [p.id for p in catalog.search(query)]
        self.assertEqual(ids("wi")[0], "wifi")
        self.assertEqual(ids("volume"), ["sound"])
        self.assertEqual(ids("dark")[0], "appearance")
        self.assertIn("start", ids("pin"))
        self.assertEqual(ids("resolution")[0], "displays")
        self.assertEqual(ids("Lock")[0], "privacy", "case-insensitive, title words first")
        self.assertEqual(ids("printer")[0], "printers")
        self.assertEqual(ids("time zone"), ["datetime"])
        self.assertEqual(ids("zzz"), [])
        self.assertEqual(ids(""), list(catalog.PAGE_IDS))

    def test_page_lookup_and_argument(self):
        self.assertEqual(catalog.page("sound").title, "Sound")
        self.assertEqual(catalog.page("advanced").id, "about", "old page names still open something")
        self.assertIsNone(catalog.page("nope"))
        self.assertEqual(catalog.page_argument(["--page", "wifi"]), "wifi")
        self.assertEqual(catalog.page_argument(["--page=bluetooth"]), "bluetooth")
        self.assertIsNone(catalog.page_argument(["--page"]))
        self.assertIsNone(catalog.page_argument([]))

    def test_duration_labels(self):
        self.assertEqual(catalog.duration_label(0), "Never")
        self.assertEqual(catalog.duration_label(30), "30 seconds")
        self.assertEqual(catalog.duration_label(60), "1 minute")
        self.assertEqual(catalog.duration_label(3600), "1 hour")
        self.assertEqual(catalog.duration_label(5400), "90 minutes")

    def test_access_point_security(self):
        ccmp = 0x8
        sec = catalog.ap_security
        self.assertFalse(sec(0, 0, 0)["secure"], "open network")
        self.assertFalse(sec(0, 0, catalog.KEY_MGMT_OWE | ccmp)["secure"], "OWE needs no password")
        wpa2 = sec(catalog.AP_PRIVACY, 0, catalog.KEY_MGMT_PSK | ccmp)
        self.assertTrue(wpa2["secure"])
        self.assertFalse(wpa2["sae_only"] or wpa2["enterprise"] or wpa2["wep"])
        self.assertTrue(sec(catalog.AP_PRIVACY, 0, catalog.KEY_MGMT_SAE | ccmp)["sae_only"])
        transition = sec(catalog.AP_PRIVACY, 0, catalog.KEY_MGMT_SAE | catalog.KEY_MGMT_PSK | ccmp)
        self.assertFalse(transition["sae_only"], "WPA2/WPA3 transition networks accept WPA-PSK")
        self.assertTrue(sec(catalog.AP_PRIVACY, 0, catalog.KEY_MGMT_802_1X | ccmp)["enterprise"])
        wep = sec(catalog.AP_PRIVACY, 0, 0)
        self.assertTrue(wep["secure"] and wep["wep"])

    def test_wifi_networks(self):
        networks = catalog.wifi_networks([
            {"ssid": "Home", "strength": 40}, {"ssid": "Home", "strength": 80}, {"ssid": None, "strength": 99},
            {"ssid": "cafe", "strength": 80}, {"ssid": "Attic", "strength": 10}])
        self.assertEqual([(n["ssid"], n["strength"]) for n in networks], [("cafe", 80), ("Home", 80), ("Attic", 10)])
        self.assertEqual(catalog.signal_icon(10), "network-wireless-signal-weak-symbolic")

    def test_ip_parsing(self):
        self.assertEqual(catalog.parse_ipv4("192.168.1.20/24"), ("192.168.1.20", 24))
        for bad in ("192.168.1.20", "192.168.1.0/24", "300.1.1.1/24", "10.0.0.1/32"):
            with self.subTest(address=bad):
                self.assertRaises(ValueError, catalog.parse_ipv4, bad)
        self.assertEqual(catalog.parse_ipv4_list("1.1.1.1, 9.9.9.9;8.8.8.8"), ["1.1.1.1", "9.9.9.9", "8.8.8.8"])
        self.assertEqual(catalog.parse_ipv4_list(""), [])
        self.assertRaises(ValueError, catalog.parse_ipv4_list, "1.1.1")
        self.assertEqual(catalog.vpn_import_type("/home/a/Office.OVPN"), "openvpn")
        self.assertEqual(catalog.vpn_import_type("wg0.conf"), "wireguard")
        self.assertIsNone(catalog.vpn_import_type("notes.txt"))

    def test_sound_devices_from_pw_dump(self):
        devices = catalog.parse_pw_dump(PW_DUMP)
        self.assertEqual([d["id"] for d in devices["sinks"]], [58])
        self.assertEqual([d["id"] for d in devices["sources"]], [59])
        self.assertEqual(devices["default_sink"], "alsa_output.pci-0000_02_02.0.analog-stereo")
        self.assertEqual(catalog.parse_pw_dump("not json")["sinks"], [])
        self.assertEqual(catalog.parse_wpctl_volume("Volume: 0.40 [MUTED]\n"), (0.4, True))
        self.assertIsNone(catalog.parse_wpctl_volume(""))

    def test_printers(self):
        printers = catalog.parse_lpstat_printers(
            "printer Office is idle.  enabled since Sat 18 Oct 2026\n"
            "printer Lab disabled since Sat 18 Oct 2026 -\n\treason unknown\n")
        self.assertEqual(printers, [{"name": "Office", "state": "idle", "enabled": True},
                                    {"name": "Lab", "state": "disabled", "enabled": False}])
        self.assertEqual(catalog.parse_lpstat_default("system default destination: Office\n"), "Office")
        self.assertIsNone(catalog.parse_lpstat_default("no system default destination\n"))
        self.assertEqual(catalog.parse_lpinfo("network ipp\nnetwork https\ndirect usb://HP/LJ?serial=1\n"
                                              "network dnssd://Brother._ipp._tcp.local/\n"),
                         [{"uri": "usb://HP/LJ?serial=1", "kind": "direct"},
                          {"uri": "dnssd://Brother._ipp._tcp.local/", "kind": "network"}])
        self.assertEqual(catalog.printer_name("HP LaserJet (2nd floor)"), "HP_LaserJet_2nd_floor")

    def test_sharing_and_time(self):
        self.assertEqual(catalog.static_hostname("Jero's Laptop"), "Jeros-Laptop")
        self.assertEqual(catalog.static_hostname("!!!"), "localhost")
        self.assertEqual(catalog.parse_grdctl_status(GRDCTL_STATUS), {"rdp": False, "port": 3389})
        self.assertEqual(catalog.parse_grdctl_status(GRDCTL_STATUS.replace("disabled", "enabled"))["rdp"], True)
        self.assertEqual(catalog.timezone_parts("America/Argentina/Buenos_Aires"), ("America", "Buenos Aires"))
        zones = ["Asia/Kolkata", "America/New_York", "Europe/Berlin"]
        self.assertEqual(catalog.search_timezones(zones, "new york"), ["America/New_York"])
        self.assertEqual(catalog.search_timezones(zones, ""), zones)

    def test_keyboard_helpers(self):
        self.assertEqual(catalog.accelerator_label("<Super><Shift>t"), "Super+Shift+T")
        self.assertEqual(catalog.accelerator_label("<Primary><Alt>Delete"), "Ctrl+Alt+Delete")
        self.assertEqual(catalog.accelerator_label(""), "Disabled")
        base = catalog.CUSTOM_KEYBINDINGS_BASE
        self.assertEqual(catalog.new_custom_keybinding_path([]), f"{base}custom0/")
        self.assertEqual(catalog.new_custom_keybinding_path([f"{base}custom0/", f"{base}custom2/"]),
                         f"{base}custom1/")
        self.assertEqual(catalog.move_item(["a", "b", "c"], 2, -1), ["a", "c", "b"])
        self.assertEqual(catalog.move_item(["a", "b"], 0, -1), ["a", "b"])
        self.assertEqual(catalog.move_item(["a"], 5, 1), ["a"])

    def test_users(self):
        self.assertIsNone(catalog.valid_username("ada"))
        for bad in ("", "Ada", "1ada", "a b", "x" * 33):
            with self.subTest(name=bad):
                self.assertIsNotNone(catalog.valid_username(bad))
        self.assertEqual(catalog.username_from_full_name("Ada Lovelace"), "ada")
        self.assertEqual(catalog.username_from_full_name("  "), "")

    def test_move_among_visible_pins(self):
        ids = ["a", "gone", "b", "c"]
        visible = ["a", "b", "c"]
        self.assertEqual(catalog.move_among(ids, visible, "b", -1), ["b", "gone", "a", "c"])
        self.assertEqual(catalog.move_among(ids, visible, "b", 1), ["a", "gone", "c", "b"])
        self.assertEqual(catalog.move_among(ids, visible, "a", -1), ids)
        self.assertEqual(ids, ["a", "gone", "b", "c"], "argument unchanged")


class ControlCenterListTests(unittest.TestCase):
    def test_module_lists_agree(self):
        python_ids = [m for m, _, _ in catalog.CONTROL_CENTER_MODULES]
        js = (ROOT / "desktop" / "extensions" / "jeronix-dock" / "cc-model.js").read_text(encoding="utf-8")
        js_ids = re.findall(r"^\s*\['([\w-]+)', \d+, \d+\],", js, re.M)
        self.assertEqual(python_ids, js_ids, "Settings and the Control Center list the same modules")
        default = ET.parse(SCHEMAS["DOCK_SCHEMA"]).getroot().find(".//key[@name='control-center-modules']/default")
        self.assertEqual(python_ids, ast.literal_eval(default.text), "the default shows every module in order")

    def test_toggle_module_keeps_catalog_order(self):
        self.assertEqual(catalog.toggle_module(["wifi", "sound"], "focus", True), ["wifi", "focus", "sound"])
        self.assertEqual(catalog.toggle_module(["wifi", "sound"], "settings", True), ["wifi", "sound", "settings"])
        self.assertEqual(catalog.toggle_module(["sound", "wifi"], "focus", True), ["sound", "wifi", "focus"],
                         "a user's own order is kept")
        self.assertEqual(catalog.toggle_module(["wifi", "sound"], "wifi", False), ["sound"])
        self.assertEqual(catalog.toggle_module(["wifi"], "nope", True), ["wifi"])


class DisplayModelTests(unittest.TestCase):
    def state(self):
        return DM.parse_state(MUTTER_STATE)

    def test_parse(self):
        serial, monitors, layout = self.state()
        self.assertEqual((serial, layout), (1, DM.LAYOUT_LOGICAL))
        self.assertEqual([m.connector for m in monitors], ["Virtual-1", "HDMI-1"], "left to right")
        vm = monitors[0]
        self.assertTrue(vm.enabled and vm.primary)
        self.assertEqual((vm.mode_id, vm.scale), ("2560x1600@59.987", 1.25))
        self.assertEqual(vm.resolutions(), [(4096, 2160), (2560, 1600), (1920, 1080)])
        self.assertEqual([m.id for m in vm.rates((2560, 1600))], ["2560x1600@59.987", "2560x1600@59.972"])

    def test_arrangement_has_no_gaps(self):
        serial, monitors, layout = self.state()
        args = DM.apply_arguments(serial, monitors, layout, DM.METHOD_VERIFY)
        self.assertEqual(args[0:2], (1, DM.METHOD_VERIFY))
        logical = args[2]
        # 2560/1.25 = 2048 logical pixels wide, so HDMI-1 starts there.
        self.assertEqual([(x, y) for x, y, *_ in logical], [(0, 0), (2048, 0)])
        self.assertEqual(logical[0][5], [("Virtual-1", "2560x1600@59.987", {})])
        self.assertEqual(args[3], {"layout-mode": 1})

    def test_rotation_and_physical_layout(self):
        serial, monitors, _ = self.state()
        monitors[0].transform = 1  # 90°: 1600 wide
        args = DM.apply_arguments(serial, monitors, DM.LAYOUT_PHYSICAL)
        self.assertEqual([(x, y) for x, y, *_ in args[2]], [(0, 0), (1600, 0)])

    def test_order_and_disabling(self):
        serial, monitors, layout = self.state()
        monitors.reverse()
        args = DM.apply_arguments(serial, monitors, layout)
        self.assertEqual([specs[0][0] for *_, specs in args[2]], ["HDMI-1", "Virtual-1"])
        self.assertEqual([x for x, *_ in args[2]], [0, 1920])
        monitors[0].enabled = False
        self.assertEqual(len(DM.apply_arguments(serial, monitors, layout)[2]), 1)

    def test_problems_are_reported(self):
        serial, monitors, layout = self.state()
        for m in monitors:
            m.enabled = False
        self.assertRaises(ValueError, DM.apply_arguments, serial, monitors, layout)
        serial, monitors, layout = self.state()
        monitors[1].primary = True
        self.assertIn("Exactly one display must be the primary display.", DM.problems(monitors))
        serial, monitors, layout = self.state()
        monitors[0].scale = 3.0
        self.assertTrue(DM.problems(monitors))

    def test_nearest_scale(self):
        _, monitors, _ = self.state()
        mode = monitors[0].modes[3]  # 1920x1080: 1, 1.25, 1.5, 2
        self.assertEqual(DM.nearest_scale(mode, 1.3333), 1.25)
        self.assertEqual(DM.nearest_scale(mode, 2.6667), 2.0)
        self.assertEqual(DM.scale_label(1.25), "125 %")


class PagesSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in PAGE_MODULES}
        cls.functions = {stem: {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
                         for stem, tree in cls.trees.items()}

    def _assigned(self, name, module="pages"):
        for node in self.trees[module].body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
                return node.value
        self.fail(f"{name} not found in {module}.py")

    def test_every_page_has_a_builder(self):
        aliases = {"network": "pages_network", "devices": "pages_devices", "people": "pages_people"}
        builders = self._assigned("BUILDERS")
        self.assertEqual(sorted(k.value for k in builders.keys), sorted(catalog.PAGE_IDS))
        for value in builders.values:
            with self.subTest(builder=ast.unparse(value)):
                if isinstance(value, ast.Attribute):
                    self.assertIn(value.attr, self.functions[aliases[value.value.id]])
                else:
                    self.assertIn(value.id, self.functions["pages"])

    def test_bound_keys_were_checked(self):
        # A row binds a key; W.settings()/W.extension_settings() only checked
        # the keys passed to them. Binding any other key could abort the app.
        for module, functions in self.functions.items():
            for func in functions.values():
                names = {}
                for node in ast.walk(func):
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                        for kind, first in (("settings", 1), ("extension_settings", 2), ("relocatable", 2)):
                            if is_w_call(node.value, kind):
                                for target in node.targets:
                                    if isinstance(target, ast.Name):
                                        names[target.id] = set(literal_strings(node.value.args[first:]))
                for node in ast.walk(func):
                    if not any(is_w_call(node, b) for b in ROW_BUILDERS):
                        continue
                    source, key = node.args[1], node.args[2]
                    if not isinstance(key, ast.Constant):
                        continue  # loop variables: checked with has_key at run time
                    with self.subTest(module=module, function=func.name, key=key.value):
                        if is_w_call(source, "settings"):
                            self.assertIn(key.value, literal_strings(source.args[1:]))
                        elif isinstance(source, ast.Name):
                            self.assertIn(key.value, names.get(source.id, set()),
                                          f"{source.id} was not checked for {key.value}")
                        else:
                            self.fail("rows must take W.settings(...) or a checked settings variable")

    def test_extension_keys_exist(self):
        keys = {name: schema_keys(path) for name, path in SCHEMAS.items()}
        for module, tree in self.trees.items():
            for node in ast.walk(tree):
                if is_w_call(node, "extension_settings"):
                    schema = node.args[1].id
                    for key in literal_strings(node.args[2:]):
                        with self.subTest(module=module, schema=schema, key=key):
                            self.assertIn(key, keys[schema])
        for key, _ in ast.literal_eval(self._assigned("TASKBAR_ITEMS")):
            with self.subTest(taskbar_item=key):
                self.assertIn(key, keys["DOCK_SCHEMA"])

    def test_no_handoff_to_gnome_settings(self):
        for path in [*PAGE_MODULES, SETTINGS_DIR / "settings.py", SETTINGS_DIR / "widgets.py"]:
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("gnome-control-center", text)
                self.assertNotIn("open_gnome_settings", text)

    def test_system_keys_exist_in_installed_schemas(self):
        if not HAVE_GI:
            self.skipTest("PyGObject not installed")
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        pairs = set()
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if is_w_call(node, "settings") and isinstance(node.args[0], ast.Constant):
                    schema, *keys = literal_strings(node.args)
                    pairs.update((schema, k) for k in keys)
                elif is_w_call(node, "settings") and isinstance(node.args[0], ast.JoinedStr):
                    # f"org.gnome.system.proxy.{scheme}": check every scheme the page uses.
                    for scheme in ("http", "https"):
                        pairs.update((f"org.gnome.system.proxy.{scheme}", k) for k in literal_strings(node.args[1:]))
                elif is_w_call(node, "relocatable") and literal_strings(node.args[:1]):
                    # (schema, path, keys...); the schema may also be a variable.
                    schema = literal_strings(node.args[:1])[0]
                    pairs.update((schema, k) for k in literal_strings(node.args[2:]))
        self.assertTrue(pairs)
        if source is None or source.lookup("org.gnome.desktop.interface", True) is None:
            self.skipTest("GNOME schemas not installed")
        for schema, key in sorted(pairs):
            with self.subTest(schema=schema, key=key):
                found = source.lookup(schema, True)
                self.assertIsNotNone(found)
                self.assertTrue(found.has_key(key))


class SymbolicIconTests(unittest.TestCase):
    def test_icons_are_up_to_date(self):
        for path, text in jeronix_symbolic.outputs().items():
            with self.subTest(icon=path.name):
                self.assertTrue(path.is_file(), "run scripts/jeronix_symbolic.py build")
                self.assertEqual(path.read_text(encoding="utf-8"), text, "run scripts/jeronix_symbolic.py build")

    def test_every_page_and_control_center_glyph_has_an_icon(self):
        self.assertEqual(sorted(jeronix_symbolic.SETTINGS), sorted(catalog.PAGE_IDS))
        cc = (ROOT / "desktop" / "extensions" / "jeronix-dock" / "control-center.js").read_text(encoding="utf-8")
        for name in set(re.findall(r"this\._icon\('([\w-]+)'\)", cc)):
            with self.subTest(glyph=name):
                self.assertIn(name, jeronix_symbolic.CONTROL_CENTER)

    def test_icons_are_fill_only(self):
        # Symbolic icons are recolored by forcing fill; strokes would break.
        for path in jeronix_symbolic.outputs():
            with self.subTest(icon=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("stroke", text)
                ET.fromstring(text)


@unittest.skipUnless(HAVE_GI, "PyGObject not installed")
class BluetoothAgentTests(unittest.TestCase):
    """The agent's answers to BlueZ, with fake D-Bus invocations."""

    class Invocation:
        def __init__(self):
            self.value = self.error = "unanswered"

        def return_value(self, value):
            self.value = value

        def return_dbus_error(self, name, message):
            self.error = name

    class UI:
        def __init__(self, answer):
            self.answer, self.cancelled, self.shown = answer, False, None

        def confirm(self, name, text, answer):
            self.text = text
            answer(self.answer)

        def ask_code(self, name, numeric, answer):
            answer(self.answer)

        def show_code(self, name, code):
            self.shown = code

        def cancel(self):
            self.cancelled = True

    def call(self, method, signature, args, answer=True):
        from gi.repository import GLib
        from settings import system
        ui = self.UI(answer)
        agent = system.BluetoothAgent(None, ui, lambda path: "Headphones")
        invocation = self.Invocation()
        agent.handle(None, ":1.1", system.AGENT_PATH, "org.bluez.Agent1", method,
                     GLib.Variant(signature, args), invocation)
        return invocation, ui

    def test_confirmation(self):
        inv, ui = self.call("RequestConfirmation", "(ou)", ("/org/bluez/hci0/dev_1", 42))
        self.assertIsNone(inv.value)
        self.assertIn("000042", ui.text)
        inv, _ = self.call("RequestConfirmation", "(ou)", ("/org/bluez/hci0/dev_1", 42), answer=False)
        self.assertEqual(inv.error, "org.bluez.Error.Rejected")

    def test_codes(self):
        inv, _ = self.call("RequestPinCode", "(o)", ("/org/bluez/hci0/dev_1",), answer="0000")
        self.assertEqual(inv.value.unpack(), ("0000",))
        inv, _ = self.call("RequestPasskey", "(o)", ("/org/bluez/hci0/dev_1",), answer="123456")
        self.assertEqual(inv.value.unpack(), (123456,))
        inv, _ = self.call("RequestPasskey", "(o)", ("/org/bluez/hci0/dev_1",), answer=None)
        self.assertEqual(inv.error, "org.bluez.Error.Rejected")
        inv, ui = self.call("DisplayPasskey", "(ouq)", ("/org/bluez/hci0/dev_1", 7, 0))
        self.assertEqual(ui.shown, "000007")

    def test_cancel_and_unknown(self):
        inv, ui = self.call("Cancel", "()", ())
        self.assertTrue(ui.cancelled)
        inv, _ = self.call("Frobnicate", "()", ())
        self.assertEqual(inv.error, "org.bluez.Error.NotSupported")


class ExtensionKeyTests(unittest.TestCase):
    def test_dock_javascript_uses_existing_keys(self):
        keys = schema_keys(SCHEMAS["DOCK_SCHEMA"])
        pattern = re.compile(r"settings\.(?:get|set|reset)_?\w*\('([\w-]+)'|'(start-[\w-]+)'|'(control-center-[\w-]+)'")
        used = set()
        for js in (ROOT / "desktop" / "extensions" / "jeronix-dock").glob("*.js"):
            for match in pattern.finditer(js.read_text(encoding="utf-8")):
                used.add(next(g for g in match.groups() if g))
        self.assertTrue({"start-pinned-apps", "start-hidden-apps", "control-center-modules",
                         "control-center-reduce-transparency"} <= used)
        self.assertEqual(sorted(used - keys), [])



class FakeScale:
    """What W.Follow uses of a Gtk.Scale."""

    def __init__(self, value=0.0):
        self.value = value
        self.handlers = {}

    def connect(self, signal, callback):
        self.handlers[signal] = callback

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value
        self.handlers["value-changed"](self)

    def drag(self, value):
        self.set_value(value)


class LiveWidgetListTests(unittest.TestCase):
    def test_widgets_toggle_in_their_order_and_keep_the_users_order(self):
        order = ["clock", "media", "weather", "system", "battery"]
        self.assertEqual(catalog.toggle_in_order(["system", "clock"], "media", True, order),
                         ["system", "clock", "media"], "after the last earlier one")
        self.assertEqual(catalog.toggle_in_order(["system", "clock"], "battery", True, order),
                         ["system", "clock", "battery"])
        self.assertEqual(catalog.toggle_in_order(["clock", "system"], "clock", False, order), ["system"])
        self.assertEqual(catalog.toggle_in_order(["clock", "bogus"], "nope", True, order), ["clock"],
                         "unknown ids are dropped and never added")
        self.assertEqual(catalog.toggle_in_order([], "weather", True, order), ["weather"])

    def test_settings_widgets_match_the_taskbar(self):
        import re
        src = (ROOT / "desktop/extensions/jeronix-dock/live-model.js").read_text(encoding="utf-8")
        js = re.findall(r"'(\w+)'", re.search(r"export const WIDGETS = \[(.*?)\]", src).group(1))
        pages_src = (ROOT / "apps/settings/pages.py").read_text(encoding="utf-8")
        py = re.findall(r'\("(\w+)", "', pages_src[pages_src.index("LIVE_WIDGETS = "):
                                                   pages_src.index("LIVE_ACTIVITIES = ")])
        self.assertEqual(py, js)
        schema = (ROOT / "desktop/extensions/jeronix-dock/schemas/org.gnome.shell.extensions.jeronix-dock.gschema.xml"
                  ).read_text(encoding="utf-8")
        default = re.search(r'<key name="live-widgets".*?<default>\[(.*?)\]</default>', schema, re.S).group(1)
        self.assertEqual(re.findall(r"'(\w+)'", default), js)


class LiveActivityListTests(unittest.TestCase):
    def test_settings_activities_match_the_taskbar(self):
        import re
        src = (ROOT / "desktop/extensions/jeronix-dock/live-model.js").read_text(encoding="utf-8")
        groups = re.search(r"export const ACTIVITY_GROUPS = \{(.*?)\n\};", src, re.S).group(1)
        js = re.findall(r"^\s+'?([\w-]+)'?: \[", groups, re.M)
        pages_src = (ROOT / "apps/settings/pages.py").read_text(encoding="utf-8")
        block = pages_src[pages_src.index("LIVE_ACTIVITIES = ("):pages_src.index("ACCENTS = ")]
        py = re.findall(r'\("([\w-]+)", "', block)
        self.assertEqual(sorted(py), sorted(js), "every activity has a switch, and only those")
        schema = (ROOT / "desktop/extensions/jeronix-dock/schemas/org.gnome.shell.extensions.jeronix-dock.gschema.xml"
                  ).read_text(encoding="utf-8")
        default = re.search(r'<key name="live-activities".*?<default>\[(.*?)\]</default>', schema, re.S).group(1)
        self.assertEqual(sorted(re.findall(r"'([\w-]+)'", default)), sorted(js), "all on by default")


class HardwareDetectionTests(unittest.TestCase):
    """Settings shows hardware controls only where the hardware exists."""

    def test_touchpads_are_counted_from_the_udev_database(self):
        import tempfile
        try:
            from settings import system
        except (ImportError, ValueError) as e:
            raise unittest.SkipTest(f"system unavailable: {e}")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "c13:64").write_text("I:1\nE:ID_INPUT=1\nE:ID_INPUT_MOUSE=1\n", encoding="utf-8")
            Path(d, "c13:65").write_text("E:ID_INPUT=1\nE:ID_INPUT_TOUCHPAD=1\nG:seat\n", encoding="utf-8")
            Path(d, "c13:66").write_text("E:ID_INPUT_TOUCHPAD=0\n", encoding="utf-8")
            Path(d, "+input:input5").write_text("E:ID_INPUT_TOUCHPAD=1\n", encoding="utf-8")  # not a device node
            self.assertEqual(system.input_devices_with("ID_INPUT_TOUCHPAD", d), 1)
            self.assertEqual(system.input_devices_with("ID_INPUT_MOUSE", d), 1)
            self.assertEqual(system.input_devices_with("ID_INPUT_TABLET", d), 0)
        self.assertIsNone(system.input_devices_with("ID_INPUT_TOUCHPAD", "/nonexistent/udev"))


class LiveSliderTests(unittest.TestCase):
    """The helpers that make Settings sliders apply and follow in real time."""

    @classmethod
    def setUpClass(cls):
        try:
            from settings import widgets
        except (ImportError, ValueError) as e:  # GTK 4 / libadwaita missing
            raise unittest.SkipTest(f"widgets unavailable: {e}")
        cls.W = widgets

    def pump(self, seconds):
        import time
        import warnings
        from gi.repository import GLib
        end = time.monotonic() + seconds
        with warnings.catch_warnings():  # PyGObject's own asyncio deprecation notice
            warnings.simplefilter("ignore", DeprecationWarning)
            while time.monotonic() < end:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)

    def test_latest_sends_now_and_only_the_newest_while_busy(self):
        sent, answers = [], []
        queue = self.W.latest(lambda value, done: (sent.append(value), answers.append(done)))
        queue(0.1)
        self.assertEqual(sent, [0.1], "the first value goes out at once")
        for v in (0.2, 0.3, 0.4):
            queue(v)
        self.assertEqual(sent, [0.1], "nothing piles up while a send is in flight")
        answers.pop(0)()
        self.assertEqual(sent, [0.1, 0.4], "then only the newest value is sent")
        answers.pop(0)()
        queue(0.5)
        self.assertEqual(sent, [0.1, 0.4, 0.5])

    def test_latest_recovers_from_a_failed_send(self):
        calls = []

        def send(value, done):
            calls.append(value)
            if value == "bad":
                raise RuntimeError("service gone")
            done()
        queue = self.W.latest(send)
        with self.assertRaises(RuntimeError):
            queue("bad")
        queue("good")
        self.assertEqual(calls, ["bad", "good"])

    def test_follow_stores_moves_and_shows_outside_changes(self):
        stored = []
        scale = FakeScale(0.5)
        follow = self.W.Follow(scale, stored.append)
        scale.drag(0.6)
        self.assertEqual(stored, [0.6], "moving the slider applies immediately")
        follow.show(0.9)
        self.assertEqual(scale.value, 0.6, "no jump under the pointer while dragging")
        self.pump(follow.QUIET_US / 1e6 + 0.15)
        self.assertEqual(scale.value, 0.9, "the outside value is shown once the drag stops")
        self.assertEqual(stored, [0.6], "showing an outside value does not send it back")
        follow.show(0.2)
        self.assertEqual(scale.value, 0.2, "outside changes show at once when not dragging")
        self.assertEqual(stored, [0.6])

    def test_follow_keeps_only_the_last_outside_value_during_a_drag(self):
        scale = FakeScale(0.0)
        follow = self.W.Follow(scale, lambda v: None)
        scale.drag(0.3)
        for v in (0.1, 0.7, 0.4):
            follow.show(v)
        self.pump(follow.QUIET_US / 1e6 + 0.15)
        self.assertEqual(scale.value, 0.4)


if __name__ == "__main__":
    unittest.main()
