# JERONIX applications

GTK 4 / libadwaita 1.9 applications in Python (PyGObject), styled from the
design tokens by [jeronix_common/style.py](jeronix_common/style.py), which
overrides libadwaita's CSS variables for JERONIX windows only.

| App | ID | Entry point | What it does |
| --- | --- | --- | --- |
| JERONIX Launcher | `io.jeronix.Launcher` | [launcher/launcher.py](launcher/launcher.py) | Search-first launcher: type to search, Enter launches. Categories, favorites (the dock's) and recently used apps. Opened by Super+J, the JERONIX menu and the dock's Applications button |
| Layout Studio | `io.jeronix.LayoutStudio` | [layout_studio/studio.py](layout_studio/studio.py) | Previews of Pure, Classic and Studio drawn from the layout data, the exact list of changes against your current settings, Apply (snapshot first, Undo toast) and Restore |
| JERONIX Settings | `io.jeronix.Settings` | [settings/settings.py](settings/settings.py) | All of the system's settings in one window, laid out like macOS System Settings, with JERONIX's own icons ([settings/icons/](settings/icons), made by `scripts/jeronix_symbolic.py`): Wi-Fi (including hidden and enterprise networks), Bluetooth (pairing), Network (wired IPv4, VPN import, proxy), Notifications (per app), Sound (devices), Appearance (accent, fonts), Wallpaper, Control Center (modules, order), Desktop & Taskbar, Start Menu, Displays (resolution, refresh rate, scale, rotation, arrangement, Night Light), Multitasking, Accessibility, Power & Battery, Lock Screen & Privacy, Search, Users, Language & Region, Date & Time, Keyboard (layouts, custom shortcuts), Mouse & Touchpad, Printers, Sharing, Default Apps, About. Nothing is handed to GNOME Settings. Changes that need permission ask through polkit. `settings.py --page NAME` opens a page |
| System Information | `io.jeronix.SystemInfo` | [system_info/sysinfo.py](system_info/sysinfo.py) | JERONIX and Ubuntu versions, kernel, GNOME/GTK/libadwaita versions, CPU, memory, disk, graphics driver, JERONIX extension states, and a copyable support report (`--report` prints it) |
| Welcome | `io.jeronix.Welcome` | [welcome/welcome.py](welcome/welcome.py) | First-run tour: introduction, light/dark, layout choice (applied with a snapshot), essential shortcuts. `--first-run` shows it only once per user |

Logic without a display lives in separate modules and is unit-tested
(`tests/unit/test_apps.py`, `tests/unit/test_settings.py`):
`launcher/catalog.py`, `settings/catalog.py`, `system_info/collect.py` and
`jeronix_common/previews.py`. `test_settings.py` also checks statically that
every settings row binds only keys it first checked to exist (GLib aborts
on an unknown key), and, on a GNOME system, that every key exists. Every app is also started on a real
headless GNOME Shell by `tests/integration/apps_lifecycle.py`.

`desktop/*.desktop.in` are menu-entry templates. `packaging/jeronix_apps.py`
stages the apps and their data (tokens, layouts, layout tool) for an
installation, and `jeronix_common/paths.py` finds that data in a checkout
or an installation.

## Not yet

- Translations (strings are English only).
- Layout Studio can't edit layouts or create new ones; it applies the
  shipped presets.
- Welcome's first-run detection is per user and per machine. There is no
  installer integration yet.
