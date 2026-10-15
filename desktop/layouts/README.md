# Layouts

A layout is a versioned JSON file of GSettings values, applied and reverted
by [scripts/jeronix_layout.py](../../scripts/jeronix_layout.py). Layouts
are data only: they cannot run commands, and they can't enable or disable
extensions. The tool writes only the keys in its allowlist (`ALLOWED`) and
checks every value against the installed GSettings schema before it changes
anything.

This is the first layout configuration, not a layout manager. Layout Studio
(Milestone 5) will build presets, previews and extension switching on top
of this format.

## Format (schema 1)

| Field | Meaning |
| --- | --- |
| `schema` | Format version, currently `1` |
| `id`, `name`, `version`, `description` | Identity. `version` is semver |
| `gnome_shell` | Supported GNOME Shell majors. Must be a subset of [config/platform.json](../../config/platform.json) |
| `settings[]` | `{schema, key, value, reason, optional?}`. `value` is JSON, or `{"asset": id}` for installed JERONIX files (`wallpaper-dark`, `wallpaper-light`) |
| `extensions.recommended[]` | `{uuid, reason}`. Shown to the user, never enabled automatically |
| `limitations[]` | What the layout cannot do |

Settings marked `optional: true` belong to extensions that might not be
installed (Ubuntu's dock and desktop icons). They are skipped when the
extension's schema is missing.

## Pure

[pure.json](pure.json) gives you a streamlined GNOME desktop: the top
panel, the Activities overview for launching and switching, an on-demand
dock and an empty desktop.

### Configured directly (GSettings)

| Schema | Key | Pure value |
| --- | --- | --- |
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
| `org.gnome.shell.extensions.dash-to-dock` | `dock-fixed` | `false` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `autohide` | `true` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `intellihide` | `true` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `dock-position` | `BOTTOM` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `extend-height` | `false` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `show-trash` | `false` (optional) |
| `org.gnome.shell.extensions.dash-to-dock` | `show-mounts` | `false` (optional) |
| `org.gnome.shell.extensions.ding` | `show-home` | `false` (optional) |
| `org.gnome.shell.extensions.ding` | `show-trash` | `false` (optional) |
| `org.gnome.shell.extensions.ding` | `show-volumes` | `false` (optional) |

### Provided by an extension

| Behavior | How |
| --- | --- |
| JERONIX panel, menus, Quick Settings, overview, search and notification styling | `jeronix-shell-theme@jeronix` (stylesheet only). You enable it yourself |

### Not done by Pure

- **The dock is not disabled.** Ubuntu's dock is the only dock, set to
  appear on demand. Turning it off, or turning off the desktop-icons
  extension, means editing the enabled-extensions list. Pure never does
  that; Layout Studio will offer it as an explicit, reversible step.
- **No second dock or panel** is added.
- **Panel contents and overview structure** can't be changed through
  GSettings. That needs a JERONIX extension in a later milestone.

### Keyboard

Pure keeps every GNOME shortcut. `Super` opens the overview, where typing
searches; `Super+A` opens the app grid; `Super+PageUp/PageDown` switches
workspaces; `Super+Left/Right` tiles windows; and `Super+number` launches
dock items. Every themed control has a visible focus ring.

## Applying and reverting

See [docs/development/desktop-identity.md](../../docs/development/desktop-identity.md).
In short:

```sh
scripts/jeronix_layout.py plan desktop/layouts/pure.json    # dry run
scripts/jeronix_layout.py apply desktop/layouts/pure.json   # saves a snapshot first
scripts/jeronix_layout.py restore                           # back to the snapshot
```
