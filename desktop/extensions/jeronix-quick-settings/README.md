# JERONIX Quick Settings

UUID: `jeronix-quick-settings@jeronix`. Supports GNOME Shell 50.

## Features

**Stay Awake** is a Quick Settings toggle. While it is on, the screen
doesn't blank and the machine doesn't suspend automatically, and a panel
icon shows that it is active.

- It uses the public `org.gnome.SessionManager.Inhibit` API with the IDLE
  and SUSPEND flags. Manual suspend and lid-close policy are not affected.
- The toggle shows the *actual* inhibitor state. If the session manager
  refuses, the toggle stays off and a notification explains why.
- Disabling the extension, logging out or a Shell crash all release the
  inhibitor. The session manager drops inhibitors when the shell's bus
  connection closes.
- The state is deliberately not remembered across sessions, so a forgotten
  toggle can't keep a laptop awake forever.

## Files

| File | Purpose |
| --- | --- |
| `extension.js` | Shell UI: toggle, panel indicator, enable/disable |
| `inhibitor.js` | Inhibit/uninhibit state machine (no Shell imports, unit-tested) |
| `metadata.json` | Manifest |

## Tests

```sh
gjs -m tests/unit/js/test_inhibitor.js            # state machine, races, failures
python3 tests/integration/extension_lifecycle.py  # real headless GNOME Shell
```

## Manual install (development)

```sh
scripts/install-extension-dev.sh jeronix-quick-settings
# Wayland: log out and back in once, then
gnome-extensions enable jeronix-quick-settings@jeronix
# check: Quick Settings shows "Stay Awake"; with it on,
gnome-session-inhibit --list    # lists jeronix-quick-settings@jeronix
# uninstall
scripts/install-extension-dev.sh --remove jeronix-quick-settings
```
