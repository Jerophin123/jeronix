# SPDX-License-Identifier: GPL-3.0-or-later
"""What JERONIX Settings contains: its pages, sidebar groups, search, and
the parsing and list rules its pages use. No GTK here, so it is unit-tested
without a display (tests/unit/test_settings.py)."""

import json
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    color: str         # one of COLORS
    group: int         # sidebar group; groups are separated by space
    keywords: tuple = field(default_factory=tuple)

    @property
    def icon(self):
        """JERONIX's own symbolic icon (apps/settings/icons)."""
        return f"jeronix-settings-{self.id}-symbolic"


# The sidebar's colored squares (macOS System Settings style). Each is dark
# enough for a white symbolic icon (contrast checked in the tests).
COLORS = {
    "blue": "#2F6FDB",
    "indigo": "#5145C8",
    "purple": "#8A3FB5",
    "pink": "#C2366E",
    "red": "#C93A31",
    "orange": "#B85C14",
    "green": "#2E7D46",
    "teal": "#1F7A80",
    "gray": "#5F6368",
}

PAGES = (
    Page("wifi", "Wi-Fi", "blue", 0, ("wireless", "wlan", "internet", "network", "airplane", "hidden", "hotspot")),
    Page("bluetooth", "Bluetooth", "blue", 0, ("wireless", "devices", "headphones", "mouse", "keyboard", "pair")),
    Page("network", "Network", "blue", 0, ("ethernet", "wired", "ip", "address", "dns", "vpn", "wireguard",
                                           "openvpn", "proxy", "internet", "connection")),

    Page("notifications", "Notifications", "red", 1, ("do not disturb", "focus", "banners", "alerts",
                                                      "lock screen", "apps")),
    Page("sound", "Sound", "pink", 1, ("volume", "speaker", "headphones", "output", "input", "microphone", "mute",
                                       "alert", "beep", "device")),

    Page("appearance", "Appearance", "gray", 2, ("dark", "light", "mode", "theme", "style", "accent", "color",
                                                 "fonts", "text size")),
    Page("wallpaper", "Wallpaper", "teal", 2, ("background", "picture", "image", "desktop")),
    Page("control-center", "Control Center", "gray", 2, ("quick settings", "toggles", "modules", "status", "tray",
                                                         "transparency")),
    Page("desktop", "Desktop & Taskbar", "indigo", 2, ("dock", "taskbar", "tray", "top bar", "panel", "layout",
                                                       "icons", "position", "title bar", "windows", "widgets", "live",
                                                       "weather", "music", "calendar")),
    Page("start", "Start Menu", "blue", 2, ("pinned", "pin", "unpin", "apps", "super", "launcher", "recommended",
                                              "hidden")),
    Page("displays", "Displays", "blue", 2, ("resolution", "refresh rate", "scale", "rotation", "orientation",
                                             "monitor", "screen", "primary", "night light", "brightness")),
    Page("multitasking", "Multitasking", "purple", 2, ("workspaces", "hot corner", "screen edges", "tiling",
                                                       "app switching", "alt tab")),
    Page("accessibility", "Accessibility", "blue", 2, ("a11y", "screen reader", "zoom", "magnifier", "contrast",
                                                       "large text", "cursor", "sticky keys", "on-screen keyboard",
                                                       "reduce motion", "visual alerts")),

    Page("power", "Power & Battery", "green", 3, ("battery", "suspend", "sleep", "blank", "screen off",
                                                  "power mode", "performance", "saver")),
    Page("privacy", "Lock Screen & Privacy", "gray", 3, ("lock", "screen lock", "location", "camera",
                                                         "microphone", "history", "recent files", "trash",
                                                         "temporary", "usb", "diagnostics")),
    Page("search", "Search", "gray", 3, ("search", "providers", "results", "apps search")),

    Page("users", "Users", "orange", 4, ("account", "password", "avatar", "picture", "administrator",
                                         "automatic login", "add user", "name")),
    Page("region", "Language & Region", "blue", 4, ("language", "locale", "formats", "region", "country",
                                                    "dates", "numbers")),
    Page("datetime", "Date & Time", "orange", 4, ("clock", "time zone", "24-hour", "12-hour", "seconds",
                                                  "weekday", "calendar", "ntp", "automatic time")),
    Page("keyboard", "Keyboard", "gray", 4, ("shortcuts", "keys", "repeat", "typing", "layout", "input sources",
                                             "custom shortcuts", "super")),
    Page("mouse", "Mouse & Touchpad", "gray", 4, ("pointer", "speed", "scroll", "natural", "tap", "click",
                                                  "trackpad", "touchpad", "middle click")),
    Page("printers", "Printers", "gray", 4, ("printer", "print", "cups", "queue", "test page", "default printer")),

    Page("sharing", "Sharing", "teal", 5, ("device name", "hostname", "computer name", "remote desktop", "rdp")),
    Page("default-apps", "Default Apps", "orange", 5, ("browser", "web", "mail", "calendar", "music", "video",
                                                       "photos", "open with", "removable media", "autorun")),
    Page("about", "About", "gray", 5, ("system", "version", "hardware", "processor", "memory", "disk", "report",
                                       "jeronix")),
)

PAGE_IDS = tuple(p.id for p in PAGES)
DEFAULT_PAGE = "appearance"
# Older page names that --page still accepts.
PAGE_ALIASES = {"advanced": "about", "display": "displays", "region-language": "region"}


def page(page_id):
    """The page with this id (or an alias of it), or None."""
    page_id = PAGE_ALIASES.get(page_id, page_id)
    return next((p for p in PAGES if p.id == page_id), None)


def search(query, pages=PAGES):
    """Pages matching every word of query, best first: title prefix, then a
    word in the title, then a keyword. Empty query: all pages in order."""
    words = query.lower().split()
    if not words:
        return list(pages)
    scored = []
    for order, p in enumerate(pages):
        title = p.title.lower()
        total = 0
        for word in words:
            if title.startswith(word):
                total += 3
            elif any(w.startswith(word) for w in title.replace("&", " ").split()):
                total += 2
            elif any(word in k for k in p.keywords):
                total += 1
            else:
                total = None
                break
        if total is not None:
            scored.append((-total, order, p))
    return [p for _, _, p in sorted(scored, key=lambda t: (t[0], t[1]))]


def page_argument(arguments):
    """The NAME of --page NAME or --page=NAME, or None."""
    for i, arg in enumerate(arguments):
        if arg == "--page" and i + 1 < len(arguments):
            return arguments[i + 1]
        if arg.startswith("--page="):
            return arg.split("=", 1)[1]
    return None


# -- durations -----------------------------------------------------------------------

def duration_label(seconds):
    """'Never', '30 seconds', '1 minute', '5 minutes', '1 hour'..."""
    if seconds <= 0:
        return "Never"
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = round(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


# Choices offered for durations (seconds). 0 means never.
BLANK_SCREEN = (60, 120, 180, 300, 600, 900, 0)
SUSPEND_AFTER = (900, 1200, 1800, 2700, 3600, 5400, 7200)
LOCK_DELAY = (0, 30, 60, 120, 180, 300, 1800, 3600)


# -- keyboard --------------------------------------------------------------------------

# The keyboard shortcuts the Keyboard page lists, as JERONIX sets them up.
SHORTCUTS = (
    ("Super", "Open or close the Start menu"),
    ("Super+J", "Open the Start menu"),
    ("Super+S", "Control Center"),
    ("Super+V", "Notifications and calendar"),
    ("Super+A", "All applications"),
    ("Alt+Tab", "Switch between applications"),
    ("Super+Left / Right", "Tile the window to half the screen"),
    ("Super+Up / Down", "Maximize or restore the window"),
    ("Super+Page Up / Down", "Previous or next workspace"),
    ("Super+L", "Lock the screen"),
    ("Print", "Take a screenshot"),
    ("Ctrl+Alt+T", "Terminal"),
    ("Ctrl+Alt+Tab", "Move keyboard focus to the taskbar"),
)

CUSTOM_KEYBINDINGS_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def new_custom_keybinding_path(existing):
    """The first free .../custom-keybindings/customN/ path."""
    used = set(existing)
    n = 0
    while f"{CUSTOM_KEYBINDINGS_BASE}custom{n}/" in used:
        n += 1
    return f"{CUSTOM_KEYBINDINGS_BASE}custom{n}/"


def accelerator_label(accelerator):
    """'<Super><Shift>t' -> 'Super+Shift+T'; '' -> 'Disabled'."""
    if not accelerator:
        return "Disabled"
    mods = re.findall(r"<([^>]+)>", accelerator)
    key = re.sub(r"<[^>]+>", "", accelerator)
    names = {"primary": "Ctrl", "control": "Ctrl", "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt",
             "super": "Super", "meta": "Meta", "hyper": "Hyper"}
    parts = [names.get(m.lower(), m) for m in mods]
    if key:
        parts.append(key.upper() if len(key) == 1 else key.replace("_", " "))
    return "+".join(parts)


def move_item(items, index, delta):
    """items with the one at index moved delta places (clamped)."""
    items = list(items)
    if not 0 <= index < len(items):
        return items
    target = max(0, min(len(items) - 1, index + delta))
    items.insert(target, items.pop(index))
    return items


# -- Start menu pins ----------------------------------------------------------------

def move_among(ids, visible, app_id, delta):
    """Pinned ids with app_id swapped with its neighbor delta (-1 or +1) steps
    away in the visible list; apps that are not shown keep their places."""
    ids = list(ids)
    if app_id not in visible or app_id not in ids:
        return ids
    j = visible.index(app_id) + delta
    if not 0 <= j < len(visible) or visible[j] not in ids:
        return ids
    a, b = ids.index(app_id), ids.index(visible[j])
    ids[a], ids[b] = ids[b], ids[a]
    return ids


# -- Control Center -----------------------------------------------------------------

# Must match MODULES in desktop/extensions/jeronix-dock/cc-model.js (tested).
CONTROL_CENTER_MODULES = (
    ("wifi", "Wi-Fi", "Network on machines without Wi-Fi"),
    ("bluetooth", "Bluetooth", "Only with a Bluetooth adapter"),
    ("airplane-mode", "Airplane Mode", "Only with wireless radios"),
    ("vpn", "VPN", "Only when a VPN is set up"),
    ("focus", "Do Not Disturb", ""),
    ("stay-awake", "Stay Awake", "Keeps the screen on and stops automatic suspend"),
    ("dark-mode", "Dark Mode", ""),
    ("night-light", "Night Light", ""),
    ("power-mode", "Power Mode", "Only when power profiles are available"),
    ("display", "Display brightness", "Only on screens with adjustable brightness"),
    ("sound", "Sound", "Volume and output device"),
    ("now-playing", "Now Playing", "When music or video is playing"),
    ("battery", "Battery", "Only on computers with a battery"),
    ("screenshot", "Screenshot", ""),
    ("screen-recording", "Screen Recording", ""),
    ("settings", "Settings", ""),
)


def toggle_module(enabled, module_id, on):
    """The enabled list with module_id turned on (in catalog order) or off."""
    return toggle_in_order(enabled, module_id, on, [m for m, _, _ in CONTROL_CENTER_MODULES])


def toggle_in_order(enabled, module_id, on, order):
    """The enabled list (ids from order) with module_id turned on or off.
    Unknown ids are dropped; the user's own order is kept."""
    current = [m for m in enabled if m in order]
    if not on:
        return [m for m in current if m != module_id]
    if module_id in current or module_id not in order:
        return current
    # Right after the last enabled module that comes before it in the
    # catalog (at the start if none does), so a user's own order is kept.
    position = order.index(module_id)
    after = max((i for i, m in enumerate(current) if order.index(m) < position), default=-1)
    return current[:after + 1] + [module_id] + current[after + 1:]


# -- Wi-Fi -------------------------------------------------------------------------------

# 802.11 access point flags (libnm NM80211ApFlags / NM80211ApSecurityFlags).
AP_PRIVACY = 0x1
KEY_MGMT_PSK = 0x100
KEY_MGMT_802_1X = 0x200
KEY_MGMT_SAE = 0x400
KEY_MGMT_OWE = 0x800


def ap_security(flags, wpa_flags, rsn_flags):
    """How to join an access point: {secure, wep, enterprise, sae_only}.

    secure means a password is needed. Open and OWE ("Enhanced Open")
    networks need none, even though OWE sets cipher bits."""
    security = wpa_flags | rsn_flags
    wep = bool(flags & AP_PRIVACY) and not security
    personal = bool(security & (KEY_MGMT_PSK | KEY_MGMT_SAE))
    enterprise = bool(security & KEY_MGMT_802_1X)
    return {"secure": personal or enterprise or wep, "wep": wep, "enterprise": enterprise,
            "sae_only": bool(security & KEY_MGMT_SAE) and not security & KEY_MGMT_PSK}


def wifi_networks(access_points):
    """Visible networks from access points [{ssid, strength, ...}], one entry
    per SSID (the strongest), strongest first, hidden (empty) SSIDs dropped."""
    best = {}
    for ap in access_points:
        ssid = ap.get("ssid")
        if not ssid:
            continue
        if ssid not in best or ap.get("strength", 0) > best[ssid].get("strength", 0):
            best[ssid] = ap
    return sorted(best.values(), key=lambda a: (-a.get("strength", 0), a["ssid"].lower()))


def signal_icon(strength):
    """Symbolic icon for a 0..100 Wi-Fi signal strength."""
    if strength >= 75:
        return "network-wireless-signal-excellent-symbolic"
    if strength >= 50:
        return "network-wireless-signal-good-symbolic"
    if strength >= 25:
        return "network-wireless-signal-ok-symbolic"
    return "network-wireless-signal-weak-symbolic"


# -- Network -----------------------------------------------------------------------------

def parse_ipv4(address):
    """'192.168.1.20/24' -> ('192.168.1.20', 24); raises ValueError."""
    import ipaddress
    text = address.strip()
    if "/" not in text:
        raise ValueError("Write the address with its prefix, for example 192.168.1.20/24.")
    interface = ipaddress.IPv4Interface(text)
    if interface.network.prefixlen in (0, 32) or interface.ip == interface.network.network_address:
        raise ValueError(f"{text} is not a usable host address.")
    return str(interface.ip), interface.network.prefixlen


def parse_ipv4_list(text):
    """'1.1.1.1, 9.9.9.9' -> ['1.1.1.1', '9.9.9.9']; raises ValueError."""
    import ipaddress
    result = []
    for part in re.split(r"[\s,;]+", text.strip()):
        if part:
            result.append(str(ipaddress.IPv4Address(part)))
    return result


VPN_FILE_TYPES = {".ovpn": "openvpn", ".conf": "wireguard"}


def vpn_import_type(filename):
    """nmcli import type for a VPN file, by extension, or None."""
    for ext, kind in VPN_FILE_TYPES.items():
        if filename.lower().endswith(ext):
            return kind
    return None


# -- Sound -------------------------------------------------------------------------------

def parse_pw_dump(text):
    """Sound devices from `pw-dump` JSON: {sinks, sources, default_sink,
    default_source}, devices as {id, name, description}."""
    try:
        objects = json.loads(text)
    except (ValueError, TypeError):
        return {"sinks": [], "sources": [], "default_sink": None, "default_source": None}
    sinks, sources, defaults = [], [], {}
    for o in objects if isinstance(objects, list) else []:
        if o.get("type") == "PipeWire:Interface:Metadata" and (o.get("props") or {}).get("metadata.name") == "default":
            for entry in o.get("metadata") or []:
                value = entry.get("value")
                if isinstance(value, dict) and entry.get("key") in ("default.audio.sink", "default.audio.source"):
                    defaults[entry["key"]] = value.get("name")
            continue
        props = (o.get("info") or {}).get("props") or {}
        kind = props.get("media.class")
        if kind not in ("Audio/Sink", "Audio/Source"):
            continue
        device = {"id": o.get("id"), "name": props.get("node.name"),
                  "description": props.get("node.description") or props.get("node.nick") or props.get("node.name")}
        if device["id"] is None or not device["name"]:
            continue
        (sinks if kind == "Audio/Sink" else sources).append(device)
    return {"sinks": sinks, "sources": sources, "default_sink": defaults.get("default.audio.sink"),
            "default_source": defaults.get("default.audio.source")}


def parse_wpctl_volume(text):
    """(volume, muted) from `wpctl get-volume` ("Volume: 0.40 [MUTED]"), or None."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Volume:":
            try:
                volume = float(parts[1])
            except ValueError:
                return None
            return volume, "[MUTED]" in parts[2:]
    return None


# -- Printers ----------------------------------------------------------------------------

def parse_lpstat_printers(text):
    """[{name, state, enabled}] from `LC_ALL=C lpstat -p`."""
    printers = []
    for line in text.splitlines():
        m = re.match(r"^printer (\S+) (?:is (\w+)|(disabled))", line)
        if m:
            printers.append({"name": m.group(1), "state": m.group(2) or "disabled",
                             "enabled": m.group(3) is None})
    return printers


def parse_lpstat_default(text):
    """The default printer from `LC_ALL=C lpstat -d`, or None."""
    m = re.search(r"system default destination: (\S+)", text)
    return m.group(1) if m else None


def parse_lpinfo(text):
    """[{uri, kind}] of real devices from `lpinfo -v` (backends without a
    device, such as 'network ipp', are left out)."""
    devices = []
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and ("://" in parts[1] or parts[1].startswith(("usb:", "hp:"))):
            uri = parts[1].strip()
            if uri not in [d["uri"] for d in devices]:
                devices.append({"uri": uri, "kind": parts[0]})
    return devices


def printer_name(text):
    """A CUPS queue name from a free-form name: letters, digits, _ and -."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip()).strip("_")
    return name[:127] or "Printer"


# -- Sharing, Date & Time ----------------------------------------------------------------

def static_hostname(pretty):
    """The static hostname for a device name ('Jero's Laptop' -> 'Jeros-Laptop')."""
    name = re.sub(r"[^A-Za-z0-9-]+", "-", pretty.replace("'", "").strip()).strip("-")
    return name[:63].strip("-") or "localhost"


def parse_grdctl_status(text):
    """{'rdp': bool, 'port': int|None} from `grdctl status`."""
    rdp, port, section = False, None, None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and not line.startswith(("\t", " ")):
            section = stripped[:-1]
        elif section == "RDP" and stripped.startswith("Status:"):
            rdp = stripped.split(":", 1)[1].strip() == "enabled"
        elif section == "RDP" and stripped.startswith("Port:"):
            try:
                port = int(stripped.split(":", 1)[1])
            except ValueError:
                port = None
    return {"rdp": rdp, "port": port}


def timezone_parts(zone):
    """'America/Argentina/Buenos_Aires' -> ('America', 'Buenos Aires')."""
    parts = zone.split("/")
    return parts[0], parts[-1].replace("_", " ")


def search_timezones(zones, query):
    """Zones whose name matches every word of query (spaces = underscores)."""
    words = query.lower().replace("_", " ").split()
    return [z for z in zones if all(w in z.lower().replace("_", " ") for w in words)]


# -- Users ---------------------------------------------------------------------------

def valid_username(name):
    """An error message for a new account name, or None if it is valid."""
    if not name:
        return "Enter a user name."
    if len(name) > 32:
        return "The user name is too long (32 characters at most)."
    if not re.match(r"^[a-z_][a-z0-9_-]*$", name):
        return "Use lowercase letters, digits, - and _ only, starting with a letter."
    return None


def username_from_full_name(full_name):
    """'Ada Lovelace' -> 'ada' (the first word, made valid)."""
    first = (full_name.strip().split() or [""])[0].lower()
    name = re.sub(r"[^a-z0-9_-]", "", first)
    if name and not re.match(r"^[a-z_]", name):
        name = "u" + name
    return name[:32]
