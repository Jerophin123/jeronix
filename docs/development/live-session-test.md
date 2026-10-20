# Live-session test record

Real GNOME Shell 50.1 Wayland session on the development VM (user `jero`,
seat0), with the development install (`scripts/install-desktop-dev.sh`).
The settings beforehand were backed up with `dconf dump /` to
`~/jeronix-backups/dconf-before-live-test-20261017T180333Z.ini`.

## 2026-10-17, first run

| Step | Result | Evidence |
| --- | --- | --- |
| Install, then log out and in | The four JERONIX extensions were discovered (state INITIALIZED) | `gnome-extensions info` |
| `jeronix_layout.py plan pure.json` | 24 settings and 6 extension switches listed, with a snapshot path | command output |
| `jeronix_layout.py apply pure.json` | **Bug found:** `jeronix-panel` went to ERROR ("Extension point conflict … jeronix-menu"), and `ubuntu-dock` went to ERROR from its own `disable()` ("No signal connection 2 found") | `journalctl --user` |
| Cause | GNOME 50 processes extension-list changes asynchronously. Writing `disabled-extensions` and then `enabled-extensions` made two passes overlap and call `enable()` twice | `js/ui/extensionSystem.js` `_onEnabledExtensionsChanged` |
| Fix | `enable()` of every JERONIX extension ignores a repeated call, and the panel removes stale items. The layout tool waits until the shell has stopped the disabled extensions before writing `enabled-extensions`. A regression test checks the guard | `tests/unit/test_extensions.py::test_enable_is_idempotent` |
| Reinstall, then log out and in | `jeronix-shell-theme`, `-panel`, `-dock` and `-quick-settings` all ACTIVE; `ubuntu-dock` and `ding` not running; icon theme `JERONIX` | `gnome-extensions info`, `gsettings` |
| Visual check by the user | JERONIX top bar (copper J and wordmark, no Activities), copper J wallpaper, floating JERONIX dock with the user's own favorites (Firefox, Files with the JERONIX icon, App Center, Help). Ubuntu Dock gone | screenshot `~/Pictures/Screenshots/Screenshot From 2026-10-17 23-41-29.png` |
| JERONIX menu, Launcher (Super+J), Quick Settings | Reported by the user as looking right. The Launcher was opened several times (journal shows `app-gnome-io.jeronix.Launcher` scopes) | user report and journal, no screenshot |
| System Information report | Correct OS, kernel, GNOME 50.1, CPU, memory, graphics (vmwgfx), extension states | `sysinfo.py --report` in the session |

## Not yet verified in a live session

- The Windows 11 / macOS taskbar features (Start and Search buttons, pill
  indicators, magnification, labels, bounce) added after this run. They are
  covered by the headless tests (`desktop_lifecycle.py`) only.
- Window previews, intellihide and edge reveal with real windows.
- Studio and Classic layouts, and restoring to Ubuntu's desktop.
- Start menu pinning, the Control Center and JERONIX Settings in a logged-in
  session. They pass the headless shell tests (`desktop_lifecycle.py`,
  `settings_pages.py`, which opens every Settings page), and every Settings
  page was built against the real services of an Ubuntu 26.04 VM, but on
  that VM Wi-Fi, Bluetooth pairing, battery, brightness and printers could
  not be exercised (no such hardware). Bluetooth pairing, Wi-Fi joining,
  display changes, user management, and changing the time zone or time
  are therefore checked by code review and unit tests only.
- Stay Awake with the full JERONIX shell, keyboard-only navigation, and
  light mode.
