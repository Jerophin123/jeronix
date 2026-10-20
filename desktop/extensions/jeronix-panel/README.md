# JERONIX Panel

UUID: `jeronix-panel@jeronix`. Supports GNOME Shell 50.

Reshapes the left side of GNOME's top bar. GNOME's own clock, calendar,
Quick Settings, accessibility and status indicators are unchanged.

| Element | Behavior |
| --- | --- |
| **JERONIX menu** (blue J symbol and wordmark) | Replaces Activities. Items: Search Applications (JERONIX Launcher), Overview, All Applications, Layout Studio, JERONIX Settings, System Information, Welcome Tour, Lock Screen, Log Out, Power Off. Lock, log-out and power items use GNOME's `SystemActions` and are hidden when not permitted |
| **Workspaces** | Numbered pills, with the active one in blue. Click a pill to switch; scroll to step through workspaces |
| **Focused application** | Icon and name of the focused app. Click it for GNOME's app menu: its windows, new window, pin and quit |

The overview remains reachable from the menu, the Super key (unless the
JERONIX Dock gives Super to its Start menu; its Task View button then opens
the overview) and the hot corner, so hiding Activities removes no
function. Disabling the extension puts Activities back.

## Settings (`org.gnome.shell.extensions.jeronix-panel`)

| Key | Default | Meaning |
| --- | --- | --- |
| `show-menu-label` | `true` | Show "JERONIX" next to the symbol |
| `show-workspaces` | `true` | Show the workspace pills |
| `show-window-context` | `true` | Show the focused application |
| `hide-activities` | `true` | Hide GNOME's Activities button |

## Keyboard

Every element is a focusable panel button: `Ctrl+Alt+Tab` → Top Bar, then
the arrow keys and `Enter`. Menus follow GNOME's standard menu navigation.

## Tests

`tests/integration/desktop_lifecycle.py` (real headless shell) and
`tests/unit/test_extensions.py`.
