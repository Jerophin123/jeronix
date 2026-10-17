# JERONIX Dock

UUID: `jeronix-dock@jeronix`. Supports GNOME Shell 50.

A floating dock built from GNOME Shell's own application icons
(`AppDisplay.AppIcon`). Launching, window activation, running state, the
app menu (window list, new window, pin and unpin, quit) and dragging behave
exactly as in the rest of the shell.

## Features

A Windows 11 and macOS hybrid. By default it is a **full-width Windows 11
taskbar** (`style=taskbar`):

- **One bar.** GNOME's Quick Settings (network, sound, power, Stay Awake...)
  and the clock with the notification center and calendar are moved from
  the top bar into the taskbar's tray, and open upward. They are GNOME's own
  components, so every control works as before. GNOME's top bar is hidden
  (`hide-top-bar`) and comes back as soon as the extension is disabled or
  the screen locks.
- **Start menu** (Start button, Search box, **Super** or Super+J): a shell
  popup, not a window, centered on the screen just above a centered
  taskbar (above the Start button on a left-aligned one). Search on top
  (type, then Enter), Pinned apps (the dock favorites) in rows of six, All
  apps, Recommended (your most used apps that aren't pinned), and a footer
  across the bottom with your name, JERONIX Settings, Lock, Log Out and
  Power Off. Super or Escape closes it.
- **Super key**: GNOME's own handler (which opens the overview) is blocked
  while the extension is enabled and unblocked when it's disabled
  (`super-key-start-menu`).
- **Task View** opens the overview with windows and workspaces only:
  GNOME's dash and app grid button are hidden there (`hide-overview-dash`)
  and come back on disable.
- Apps are **centered** on the whole bar or **left-aligned** (`alignment`),
  and stay centered when the tray changes width.

The rest of the bar:

- **Start, Search and Task View first** (Windows 11). Start and Search
  both open the JERONIX Start menu; Search opens it ready to type.
- **Pill indicators** (Windows 11): a short neutral pill under running apps,
  which widens into copper for the focused app.
- **Magnification** (macOS): the hovered icon grows 35% and its neighbors
  15%, rising out of the bar from the screen edge.
- **Hover labels** (macOS) above icons, and a **launch bounce** for apps that
  are starting. Both are instant or off with reduced motion.
- **Floating, translucent, rounded** bar, centered and sized to its contents.
- **Favorites then running apps**, with an optional Applications button at
  the end.
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
| `style` | `taskbar` | `taskbar` (full width, bottom only), `floating` |
| `alignment` | `center` | `center`, `start` |
| `system-tray` | `true` | Quick Settings and clock in the bar (bottom only) |
| `hide-top-bar` | `true` | Hide GNOME's top bar while the bar carries the tray |
| `show-task-view-button` | `true` | Task View button |
| `start-menu-shortcut` | `['<Super>j']` | Opens the Start menu |
| `super-key-start-menu` | `true` | Super opens the Start menu (`false`: GNOME's overview) |
| `hide-overview-dash` | `true` | Hide GNOME's dash and app grid button in the overview |
| `show-start-button` | `true` | JERONIX Start button (opens the Start menu) |
| `show-search-button` | `true` | Search button (GNOME search) |
| `magnify` | `true` | Magnify icons under the pointer |
| `show-apps-button` | `false` | Applications button at the end |
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
index, taskbar row) and `tests/integration/desktop_lifecycle.py`, which
covers, in a real headless GNOME Shell: favorites, running apps, centering
(also after the tray grows), the tray, the Start menu (Super, Super+J,
Search box, placement, footer, search, closing), previews, intellihide,
edge reveal, Task View without GNOME's dash, positions, reserved space,
and teardown (tray, top bar, dash and Super key given back to GNOME).
