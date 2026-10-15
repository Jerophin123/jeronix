# JERONIX Dock

UUID: `jeronix-dock@jeronix`. Supports GNOME Shell 50.

A floating dock built from GNOME Shell's own application icons
(`AppDisplay.AppIcon`). Launching, window activation, running state, the
app menu (window list, new window, pin and unpin, quit) and dragging behave
exactly as in the rest of the shell.

## Features

- **Favorites then running apps**, separated from an Applications button
  that opens the JERONIX Launcher (or GNOME's app grid if the launcher isn't
  installed). The focused app is tinted sage and running apps get a copper
  bar.
- **Window previews**: hover a running app for live thumbnails of its
  windows on the current workspace, and named entries for windows on other
  workspaces. Click one to switch to it.
- **Drag and drop**: drop an app from the dock, the app grid or search onto
  the dock to pin or reorder favorites. Unpin from the app menu.
- **Positions**: bottom, left or right, on the primary monitor, following
  monitor changes.
- **Behavior**: `intellihide` (hidden only while a window overlaps it),
  `autohide` (shown when the pointer touches the screen edge) or `always`
  (always visible and reserves space, so maximized windows stop above it).
- **Overflow**: icons shrink in 4 px steps down to 24 px, then the app list
  scrolls.
- **Overview and fullscreen**: the dock steps aside for the overview, which
  has its own dash, and for fullscreen windows.
- **Keyboard**: `Ctrl+Alt+Tab` → Dock focuses it (revealing it if hidden).
  Arrow keys move between apps, `Enter` launches, and `Menu`/`Shift+F10`
  opens the app menu.
- **Reduced motion**: show and hide animations are instant when animations
  are disabled.

## Settings (`org.gnome.shell.extensions.jeronix-dock`)

| Key | Default | Values |
| --- | --- | --- |
| `position` | `bottom` | `bottom`, `left`, `right` |
| `behavior` | `intellihide` | `always`, `intellihide`, `autohide` |
| `icon-size` | `44` | 24–72 (preferred; shrinks to fit) |
| `show-running` | `true` | Show running non-favorite apps |
| `show-apps-button` | `true` | Show the Applications button |
| `show-previews` | `true` | Window previews on hover |

## Two docks

This extension never touches Ubuntu's dock. Layouts that use it (Pure,
Studio) turn `ubuntu-dock@ubuntu.com` off through `disabled-extensions`,
with a snapshot so `scripts/jeronix_layout.py restore` turns it back on.

## Limits (GNOME 50)

- One dock, on the primary monitor. Docks on every monitor are not
  implemented.
- Previews of windows on other workspaces show the title only, because
  hidden window actors can't be cloned.

## Tests

`gjs -m tests/unit/js/test_dock_geometry.js` (placement, fitting, drop
index) and `tests/integration/desktop_lifecycle.py`, which covers
favorites, running apps, previews, intellihide, edge reveal, overview,
positions, reserved space and teardown in a real headless GNOME Shell.
