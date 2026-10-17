# Layouts

A layout is a versioned JSON file of GSettings values and extension switches.
It is applied and reverted by
[scripts/jeronix_layout.py](../../scripts/jeronix_layout.py) and by the
Layout Studio and Welcome apps. Layouts are data only. They cannot run
commands, can write only allowlisted keys (`ALLOWED`), and can switch only
allowlisted extensions (`SWITCHABLE`: the JERONIX extensions, Ubuntu's dock
and desktop icons). Every value is checked against the installed schema
before anything changes, and an extension is enabled only if it is
installed.

## Format (schema 2)

| Field | Meaning |
| --- | --- |
| `schema` | Format version, currently `2` |
| `id`, `name`, `version`, `summary`, `description` | Identity. `version` is semver |
| `gnome_shell` | Supported GNOME Shell majors. Must be a subset of [config/platform.json](../../config/platform.json) |
| `settings[]` | `{schema, key, value, reason, optional?}`. `value` is JSON, or `{"asset": id}` for installed JERONIX files (`wallpaper-dark`, `wallpaper-light`) |
| `extensions.enable[]`, `extensions.disable[]` | Extensions to switch on or off, through `org.gnome.shell enabled-extensions` / `disabled-extensions`, which are snapshotted. Disabling happens first, so two docks never show at once |
| `extensions.recommended[]` | `{uuid, reason}`. Shown to the user, never enabled |
| `limitations[]` | What the layout cannot do |

`apply` saves a snapshot of every key it touches, including both extension
lists. `restore` refuses a snapshot that would switch any extension outside
`SWITCHABLE`.

## The layouts

| | Pure | Classic | Studio |
| --- | --- | --- | --- |
| Dock | Windows 11-style floating taskbar, bottom, always visible, 32 px | left edge, always visible (reserves space), 40 px | right edge, autohide, 36 px |
| Top bar | menu and wordmark, clock, status | menu, workspaces, focused app | symbol-only menu, workspaces, focused app |
| Workspaces | dynamic, through the overview | dynamic | 4 fixed, Super+1…4 / Super+Shift+1…4, on all monitors |
| Title bars | close only | minimize, maximize, close | minimize, maximize, close |
| Hot corner | on | off | off |
| Alt+Tab | all workspaces | all workspaces | current workspace only |
| Desktop icons | off | unchanged | off |
| Ubuntu dock | off | off | off |

### Pure settings

| Schema | Key | Pure value |
| --- | --- | --- |
| `org.gnome.desktop.interface` | `icon-theme` | `JERONIX` |
| `org.gnome.desktop.interface` | `gtk-theme` | `Yaru-sage-dark` |
| `org.gnome.desktop.interface` | `font-name` | `Noto Sans 11` |
| `org.gnome.desktop.interface` | `document-font-name` | `Noto Sans 11` |
| `org.gnome.desktop.interface` | `color-scheme` | `prefer-dark` |
| `org.gnome.desktop.interface` | `accent-color` | `slate` (Ubuntu shows it as Yaru sage) |
| `org.gnome.desktop.interface` | `enable-hot-corners` | `true` |
| `org.gnome.desktop.interface` | `clock-show-weekday` | `true` |
| `org.gnome.desktop.wm.preferences` | `button-layout` | `appmenu:close` |
| `org.gnome.mutter` | `overlay-key` | `Super` |
| `org.gnome.mutter` | `dynamic-workspaces` | `true` |
| `org.gnome.mutter` | `workspaces-only-on-primary` | `true` |
| `org.gnome.mutter` | `edge-tiling` | `true` |
| `org.gnome.desktop.background` | `picture-uri` | JERONIX light wallpaper |
| `org.gnome.desktop.background` | `picture-uri-dark` | JERONIX dark wallpaper |
| `org.gnome.desktop.background` | `picture-options` | `zoom` |
| `org.gnome.desktop.background` | `primary-color` | `#1E1D1B` |
| `org.gnome.desktop.screensaver` | `picture-uri` | JERONIX dark wallpaper |
| `org.gnome.shell.extensions.jeronix-panel` | `show-menu-label` | `true` |
| `org.gnome.shell.extensions.jeronix-panel` | `show-workspaces` | `false` |
| `org.gnome.shell.extensions.jeronix-panel` | `show-window-context` | `false` |
| `org.gnome.shell.extensions.jeronix-panel` | `hide-activities` | `true` |
| `org.gnome.shell.extensions.jeronix-dock` | `position` | `bottom` |
| `org.gnome.shell.extensions.jeronix-dock` | `behavior` | `always` |
| `org.gnome.shell.extensions.jeronix-dock` | `icon-size` | `32` |
| `org.gnome.shell.extensions.jeronix-dock` | `show-running` | `true` |
| `org.gnome.shell.extensions.jeronix-dock` | `show-previews` | `true` |

Classic and Studio list their settings, each with a reason, in
[classic.json](classic.json) and [studio.json](studio.json).

### What a layout cannot do

- Uninstall anything. Ubuntu's dock and desktop icons are only switched off.
- Change GNOME's overview structure or the order of items in the panel.
- Enable an extension that is not installed, or any extension outside
  `SWITCHABLE`.

## Applying and reverting

Use Layout Studio, or the command line:

```sh
scripts/jeronix_layout.py plan desktop/layouts/studio.json    # dry run
scripts/jeronix_layout.py apply desktop/layouts/studio.json   # saves a snapshot first
scripts/jeronix_layout.py restore                             # back to the snapshot
```

See [docs/development/desktop-identity.md](../../docs/development/desktop-identity.md).
