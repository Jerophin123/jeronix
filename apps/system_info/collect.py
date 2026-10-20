# SPDX-License-Identifier: GPL-3.0-or-later
"""System facts for JERONIX System Information. Reads files under /etc, /proc
and /sys (paths are parameters so tests can use fixtures) and a few tools
and D-Bus properties; nothing needs root and nothing is sent anywhere."""

import os
import platform
import shutil
import subprocess
from pathlib import Path

JERONIX_EXTENSIONS = ("jeronix-shell-theme@jeronix", "jeronix-panel@jeronix", "jeronix-dock@jeronix",
                      "jeronix-quick-settings@jeronix")
EXTENSION_STATES = {1: "active", 2: "inactive", 3: "error", 4: "out of date", 5: "downloading",
                    6: "initialized", 7: "deactivating", 8: "activating"}


def parse_env_file(path):
    """KEY=value files such as os-release and jeronix-release."""
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def jeronix_release(paths=("/etc/jeronix-release",)):
    for p in paths:
        values = parse_env_file(p)
        if values:
            return values
    return {}


def cpu(cpuinfo="/proc/cpuinfo"):
    model, count = None, 0
    try:
        for line in Path(cpuinfo).read_text(encoding="utf-8").splitlines():
            if line.startswith("processor"):
                count += 1
            elif line.startswith("model name") and model is None:
                model = " ".join(line.split(":", 1)[1].split())
    except OSError:
        pass
    return {"model": model or platform.processor() or "Unknown", "threads": count or os.cpu_count() or 0}


def memory_bytes(meminfo="/proc/meminfo"):
    try:
        for line in Path(meminfo).read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def disk(path="/"):
    usage = shutil.disk_usage(path)
    return {"total": usage.total, "free": usage.free}


def graphics(drm="/sys/class/drm"):
    """Kernel graphics drivers in use (vendor-neutral, no extra tools)."""
    drivers = []
    base = Path(drm)
    for card in sorted(base.glob("card[0-9]")) if base.is_dir() else []:
        driver = card / "device" / "driver"
        if driver.exists():
            name = os.path.basename(os.path.realpath(driver))
            if name not in drivers:
                drivers.append(name)
    return drivers


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def virtualization():
    value = _run(["systemd-detect-virt"]) if shutil.which("systemd-detect-virt") else ""
    return value if value and value != "none" else "none"


def gnome_shell_version():
    out = _run(["gnome-shell", "--version"]) if shutil.which("gnome-shell") else ""
    return out.replace("GNOME Shell", "").strip() or "unknown"


def session():
    return {"type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown")}


def extension_states(uuids=JERONIX_EXTENSIONS):
    """State of each JERONIX extension in the running shell, via D-Bus."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        return {u: "unknown (no session bus)" for u in uuids}
    states = {}
    for uuid in uuids:
        try:
            reply = bus.call_sync("org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions",
                                  "GetExtensionInfo", GLib.Variant("(s)", (uuid,)), None,
                                  Gio.DBusCallFlags.NONE, 3000, None)
            info = reply.unpack()[0]
            states[uuid] = EXTENSION_STATES.get(int(info.get("state", 0)), "not installed") if info else "not installed"
        except Exception:
            states[uuid] = "unknown"
    return states


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def collect(etc="/etc", proc="/proc", sys_drm="/sys/class/drm"):
    os_release = parse_env_file(Path(etc) / "os-release")
    jx = jeronix_release((Path(etc) / "jeronix-release",))
    mem = memory_bytes(Path(proc) / "meminfo")
    d = disk("/")
    return {
        "JERONIX": jx.get("VERSION", "development (not installed as a package)"),
        "Operating system": os_release.get("PRETTY_NAME", "unknown"),
        "Kernel": platform.release(),
        "Architecture": platform.machine(),
        "GNOME Shell": gnome_shell_version(),
        "Session": "{type} ({desktop})".format(**session()),
        "Processor": "{model} ({threads} threads)".format(**cpu(Path(proc) / "cpuinfo")),
        "Memory": human_bytes(mem) if mem else "unknown",
        "Disk (/)": f"{human_bytes(d['free'])} free of {human_bytes(d['total'])}",
        "Graphics driver": ", ".join(graphics(sys_drm)) or "unknown",
        "Virtualization": virtualization(),
    }


def report(info, extensions, toolkit):
    """Plain-text diagnostics report for support requests."""
    lines = ["JERONIX system report", "=" * 21, ""]
    lines += [f"{k}: {v}" for k, v in info.items()]
    lines += [f"{k}: {v}" for k, v in toolkit.items()]
    lines += ["", "JERONIX extensions:"]
    lines += [f"  {uuid}: {state}" for uuid, state in extensions.items()]
    return "\n".join(lines) + "\n"
