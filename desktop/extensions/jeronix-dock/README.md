# JERONIX Dock

UUID: `jeronix-dock@jeronix`. Supports GNOME Shell 50.

A floating dock built from GNOME Shell's own application icons
(`AppDisplay.AppIcon`). Launching, window activation, running state, the
app menu (window list, new window, pin and unpin, quit) and dragging behave
exactly as in the rest of the shell.

## Features

A Windows 11 and macOS hybrid. By default the Windows 11 taskbar is split
into **three expandable modules** (`style=modules`, `modules.js`):

- **Left**: live updates and the widgets. **Center**: Start, Search, Task
  View and the apps. **Right**: the Control Center (status icons) and the
  notification center with the calendar (clock).
- Each module floats on its own, and **expands into the panel it opens**:
  the module grows from its outer side toward the panel's width (the left
  one to the right, the right one to the left, the center one both ways),
  the panel stands directly on it, and where they meet their corners are
  square, so module and panel read as one shape. A module never grows over
  its neighbours; a panel wider than that (the notification center) stays
  flush with its module's outer edge. Closing the panel shrinks the module
  back. The growth is animated, and instant with animations turned off.
- GNOME's Control Center and notification menus are GNOME's own and keep
  all their behaviour; only their position and shape follow the module.

`style=taskbar` is the same taskbar as one full-width bar:

- **One bar.** GNOME's Quick Settings (network, sound, power, Stay Awake...)
  and the clock with the notification center and calendar are moved from
  the top bar into the taskbar's tray, and open upward. They are GNOME's own
  components, so every control works as before. GNOME's top bar is hidden
  (`hide-top-bar`) and comes back as soon as the extension is disabled or
  the screen locks.
- **Start menu** (Start button, Search box, **Super** or Super+J): a shell
  popup, not a window, centered on the screen just above a centered
  taskbar (above the Start button on a left-aligned one). Search on top
  (type, then Enter), Pinned apps in rows of six, All apps, Recommended
  (your most used apps that aren't pinned), and a footer across the bottom
  with your name, JERONIX Settings, Lock, Log Out and Power Off. Super or
  Escape closes it.
- **Pinning to Start**: Start has its own pins (`start-pinned-apps`),
  separate from the taskbar's, as in Windows 11. Right-click any app in
  Start (or press `Menu` or `Shift+F10` on it) for **Pin to Start** /
  **Unpin from Start**, **Move to front** and **Pin to taskbar** /
  **Unpin from taskbar**. JERONIX Settings → Start Menu reorders the pins.
  Apps listed in `start-hidden-apps` (by default GNOME Settings, which
  JERONIX Settings replaces) never appear in Start. Pin logic is in
  [pins.js](pins.js), without shell imports, so it is unit-tested.
- **Control Center** (macOS style): clicking the tray's status icons (or
  Super+S) opens rounded modules on a 4-column grid instead of GNOME's
  Quick Settings: Wi-Fi (the wired state on machines without Wi-Fi),
  Bluetooth, Airplane Mode and VPN in one card; Do Not Disturb, Stay Awake,
  Dark Mode, Night Light and Power Mode; Display brightness and Sound
  sliders; Now Playing (any MPRIS player); Battery; Screenshot, Screen
  Recording and Settings. Wi-Fi, Bluetooth, VPN, Sound and Power Mode open
  a list in place (networks, devices, outputs, modes), as on macOS.
  GNOME's own grid is never shown while the extension runs. Which modules
  appear and in what order is `control-center-modules`; modules whose
  hardware or service is missing are left out and the rest are packed
  without holes ([cc-model.js](cc-model.js)); the content scrolls on short
  screens. Stay Awake comes from `jeronix-quick-settings` through its
  public API. Each module uses a stable interface (libnm, gsd-rfkill, BlueZ,
  UPower, power-profiles-daemon and MPRIS over D-Bus, GSettings, and the
  shell's mixer, brightness manager and screenshot UI), checked against the
  GNOME Shell 50 sources. See [control-center.js](control-center.js).
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
  which widens into blue for the focused app.
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
- **Behavior**: `always` (the default, as on Windows 11: always visible
  and reserves its space, so maximized and snapped windows stop above it),
  `intellihide` (visible on the desktop, hidden while a window overlaps it,
  such as a maximized or snapped one, which then reaches the screen edge)
  or `autohide` (shown only when the pointer touches the screen edge).
- **One module at a time**: a hidden modules taskbar comes back module by
  module. The pointer at the bottom edge brings up only the module above
  it (the nearest one from a corner or a gap); the other two stay hidden.
  Moving along the edge swaps to the next module. A module stays up while
  the pointer is on it, or while its panel, the window previews or the
  keyboard is in it, and opening a panel by shortcut (Super, Super+S)
  brings up just its module.
- **Overflow**: icons shrink in 4 px steps down to 24 px, then the app list
  scrolls.
- **Overview and fullscreen**: the dock steps aside for the overview, which
  has its own dash, and for fullscreen windows.
- **Keyboard**: `Ctrl+Alt+Tab` → Dock focuses it (revealing it if hidden).
  Arrow keys move between apps, `Enter` launches, and `Menu`/`Shift+F10`
  opens the app menu.
- **Reduced motion**: show and hide animations are instant when animations
  are disabled.
- **Live updates** (`live.js`, logic in `live-model.js`): the left module
  shows what is going on as an icon and two short lines.
  - *Ongoing*: a screen recording (time, stop), the microphone or camera in
    use and by which apps, a low battery (with Power Saver), timers and
    focus sessions (time left, pause, stop), music (play/pause), downloads
    (name, size), Stay Awake.
  - *Glimpses*, for a moment over everything: volume or brightness, a new
    notification (click opens it), a timer done (with a chime and a
    notification), the charger plugged in or out, the network connected,
    switched or lost, a finished download (click opens it), Caps Lock.
  - *Several at once*: a "+N" shows how many more are going on; scrolling
    over the area goes through them and keeps the one chosen.
  - *Nothing going on*: notifications waiting, the weather (GNOME Weather
    set up) or "Widgets".
  - Each kind can be turned off (`live-activities`, JERONIX Settings →
    Desktop & Taskbar). Texts that tick (a timer) are updated in place, so
    a button is never replaced under the pointer.
- **The island** (inspired by the Dynamic Island and the Now Bar):
  - *Dynamic colors* (`live-colors`): the area takes the color of what is
    going on: red while recording, orange for a timer, indigo for a focus
    session or Do Not Disturb, blue for downloads, green when charging, and
    for music the album art's own color. `accent` uses the system accent
    color for everything, `neutral` none.
  - *Expand on hover* (`live-expand`): after a moment under the pointer
    the area grows, animated, with more controls: next track and the
    player's window for music, a minute more on a timer, the Downloads
    folder, dismissing a notification, turning off Stay Awake or Do Not
    Disturb; with nothing going on, quick actions (a 5-minute timer, a
    focus session, Do Not Disturb). The compact controls keep their place,
    so nothing moves under the pointer, and it grows only as far as the
    taskbar has room.
  - *Progress*: a thin bar for a song (players that report their
    position) and a timer.
  - *Motion*: glimpses pop in, the recording dot breathes, and the area
    morphs between widths; all instant with animations off.
  - *Options* (right click, Menu key or Shift+F10): Do Not Disturb, Expand
    on hover, Colors, stop showing updates like the one shown, Widgets, and
    JERONIX Settings.
  - *More updates*: Do Not Disturb on, the workspace switched to (a dot
    per workspace), microphone muted or unmuted, keyboard layout switched.
- **Widgets**: clicking the live updates opens a panel: an Activities card
  with everything going on and its controls (and the notifications
  waiting, one click from the notification center), then the clock and
  calendar, Timer (1, 5 and 10 minutes, and a 25-minute focus session with
  Do Not Disturb), Now Playing, weather, system use (processor, memory,
  disk) and battery, chosen and ordered in JERONIX Settings → Desktop &
  Taskbar. Widgets without their hardware or app are left out. Nothing is
  measured while the panel is closed. Timers survive the taskbar being
  rebuilt (a setting changed).

## Settings (`org.gnome.shell.extensions.jeronix-dock`)

| Key | Default | Values |
| --- | --- | --- |
| `position` | `bottom` | `bottom`, `left`, `right` |
| `behavior` | `always` | `always`, `intellihide`, `autohide` (modules: one module at a time) |
| `icon-size` | `44` | 24–72 (preferred; shrinks to fit) |
| `show-running` | `true` | Show running non-favorite apps |
| `style` | `modules` | `modules` (three expandable modules), `taskbar` (full width), both bottom only; `floating` |
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
| `start-pinned-apps` | Files, Firefox, Terminal, Text Editor, Settings, ... | Apps pinned to Start, in order (desktop IDs) |
| `start-hidden-apps` | GNOME Settings, Help | Apps Start never lists or finds |
| `control-center-modules` | every module | Control Center modules, in order (JERONIX Settings → Control Center) |
| `control-center-reduce-transparency` | `false` | Solid Control Center background |
| `live-updates` | `true` | Live updates and the widgets button (taskbar style) |
| `live-widgets` | clock, timer, media, weather, system, battery | Widgets, in order |
| `live-activities` | all | What the live updates show (media, timers, recording, privacy, downloads, levels, notifications, battery, network, keyboard, stay-awake, do-not-disturb, workspaces) |
| `live-colors` | `dynamic` | `dynamic` (the color of what is going on), `accent`, `neutral` |
| `live-expand` | `true` | Expand the live updates on hover, with more controls |

## Two docks

This extension never touches Ubuntu's dock. Layouts that use it (Pure,
Studio) turn `ubuntu-dock@ubuntu.com` off through `disabled-extensions`,
with a snapshot so `scripts/jeronix_layout.py restore` turns it back on.

## Limits (GNOME 50)

- One dock, on the primary monitor. Docks on every monitor are not
  implemented.
- Previews of windows on other workspaces show the title only, because
  hidden window actors can't be cloned.
- Live updates appear with the full-width taskbar only, not the floating
  dock. The weather widget needs GNOME Weather with a location; GNOME
  Shell's weather client is created once per session and shared.

## Tests

`gjs -m tests/unit/js/test_dock_geometry.js` (placement, fitting, drop
index, taskbar row, live updates), `gjs -m tests/unit/js/test_live_model.js`
(which update shows, timings, widget data), `gjs -m tests/unit/js/test_start_pins.js` (pinning,
unpinning, reordering), `gjs -m tests/unit/js/test_cc_model.js` (Control
Center layout on different hardware) and
`tests/integration/desktop_lifecycle.py`, which
covers, in a real headless GNOME Shell: favorites, running apps, centering
(also after the tray grows), the tray, the Start menu (Super, Super+J,
Search box, placement, footer, search, closing, its own pins), the Control
Center in place of the Quick Settings grid, previews, intellihide,
edge reveal, Task View without GNOME's dash, positions, reserved space,
and teardown (tray, top bar, dash and Super key given back to GNOME).
