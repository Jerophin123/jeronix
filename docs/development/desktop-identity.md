# The JERONIX desktop: install, test and roll back

This covers the JERONIX desktop layer: the shell theme, top bar, dock, Stay
Awake, icon theme, wallpapers, the five applications and the Pure, Classic
and Studio layouts. The development install is for the current user only.
No root, no system files, and no change to GDM, the system theme or the
session type.

## What changes when

| Step | Command | Effect | Logout needed? |
| --- | --- | --- | --- |
| Build | `scripts/jeronix_design.py build` | Writes derived assets to `out/` only | No |
| Install | `scripts/install-desktop-dev.sh` | Copies the four extensions, the icon theme, wallpapers, the apps and their menu entries into `~/.local/share`. Nothing is switched on | **Once**, the first time, so GNOME Shell discovers the new extensions (Wayland can't rescan in place) |
| Try a layout | Layout Studio (Activities → "Layout Studio"), or `scripts/jeronix_layout.py apply desktop/layouts/pure.json` | Saves a snapshot, then switches Ubuntu Dock off, the JERONIX extensions on, and sets the layout's settings | No. Everything applies live |
| Undo a layout | Layout Studio → Restore…, or `scripts/jeronix_layout.py restore` | Puts back exactly what the layout changed, including Ubuntu Dock | No |
| One extension on or off | `gnome-extensions enable\|disable jeronix-dock@jeronix` (or `-panel`, `-shell-theme`, `-quick-settings`), or JERONIX Settings | Live | No |
| Reinstall after changes | `scripts/install-desktop-dev.sh`, then disable and enable the changed extension | Loads the new code and style | Normally no. If the old version persists, log out and back in |
| Uninstall | `scripts/jeronix_layout.py restore`, then `scripts/install-desktop-dev.sh --remove` | Disables the extensions and deletes exactly the installed files | No |

## Manual test in a real GNOME Wayland session

Everything below has been exercised automatically in an isolated headless
GNOME Shell 50.1. The real-session test is a separate, human step, and it has
**not been performed yet** at the VM's desktop. Record each result (with
screenshots) in the milestone notes.

1. `scripts/run-tests.sh` passes.
2. `scripts/install-desktop-dev.sh`, then log out and back in.
3. Open **Layout Studio** from the app grid. Pick **Pure** → Apply.
   - The top bar shows the copper J and "JERONIX" instead of Activities.
     Ubuntu's dock is gone, and a floating dock appears at the bottom.
   - Hover a running app in the dock: a window preview appears. Maximize a
     window: the dock hides, and touching the bottom edge brings it back.
   - The JERONIX menu offers Search Applications (also **Super+J**), Layout
     Studio, Settings, System Information, Lock, Log Out and Power Off.
   - Files and folders show JERONIX icons, and the wallpaper is the copper J.
4. Apply **Studio**: four numbered workspaces in the top bar, Super+1…4
   switch between them, and the dock hides on the right edge.
5. Apply **Classic**: the dock is always visible on the left, and maximized
   windows stop beside it.
6. Quick Settings: **Stay Awake** works (with it on,
   `gnome-session-inhibit --list` shows it). Wi-Fi, sound and power controls
   are GNOME's own and behave as before.
7. Keyboard only: Ctrl+Alt+Tab reaches the top bar and the dock, the arrow
   keys move between items, and every item shows a copper focus ring.
8. Settings → Appearance → Style: switch Light/Dark. The shell, dock and
   JERONIX apps follow without a logout.
9. Layout Studio → Restore… → restore the oldest snapshot. Ubuntu's dock,
   Activities and your previous settings are back.
10. `scripts/install-desktop-dev.sh --remove`.

## Rolling back

**Something looks wrong or unreadable:**

- Layout Studio → Restore…, or `scripts/jeronix_layout.py restore`, returns
  to the settings before the last layout. Repeat to go further back.
- `gnome-extensions disable jeronix-shell-theme@jeronix` (or `-panel`,
  `-dock`) in a terminal (`Ctrl+Alt+T`) takes effect immediately.
- If the shell is unusable, open a text console with `Ctrl+Alt+F3`, log in
  and run:

  ```sh
  rm -rf ~/.local/share/gnome-shell/extensions/jeronix-*@jeronix
  dbus-run-session gsettings reset org.gnome.shell disabled-extensions   # brings Ubuntu Dock back
  ```

  Then go back with `Ctrl+Alt+F2` (or reboot) and log in again. Missing
  extensions are simply skipped.
- Last resort, no files touched: from the text console,
  `dbus-run-session gsettings set org.gnome.shell disable-user-extensions true`
  turns off **all** user extensions at the next login. Undo it later with
  `gsettings reset org.gnome.shell disable-user-extensions`.

**Snapshots** are kept in `~/.local/state/jeronix/layout-snapshots/`.
`scripts/jeronix_layout.py snapshots` lists them, and restore takes a path.
Keys that were at their default before a layout are reset rather than
written, and a snapshot can only switch JERONIX extensions, Ubuntu Dock and
desktop icons.

**Remove everything:** restore, then `scripts/install-desktop-dev.sh --remove`.
The uninstaller refuses to run while a JERONIX wallpaper or the JERONIX icon
theme is still in use, so you're never left without a wallpaper or icons.
`--force` overrides that.

## Where things go

| Item | Location |
| --- | --- |
| Sources | the repository (`design/`, `desktop/`, `apps/`, `scripts/`) |
| Generated assets | `out/` (Git-ignored), or a temporary directory during install |
| Extensions | `~/.local/share/gnome-shell/extensions/jeronix-{shell-theme,panel,dock,quick-settings}@jeronix/` |
| Icon theme | `~/.local/share/icons/JERONIX/`, with the app icons also in `~/.local/share/icons/hicolor/` |
| Wallpapers | `~/.local/share/backgrounds/jeronix/` plus `~/.local/share/gnome-background-properties/jeronix.xml` |
| Applications | `~/.local/share/jeronix/apps/`, with menu entries in `~/.local/share/applications/io.jeronix.*.desktop` |
| Shared data | `~/.local/share/jeronix/{design,layouts,scripts,config,branding}/` |
| Install record | `~/.local/share/jeronix/dev-install.manifest` |
| Runtime state | `~/.local/state/jeronix/` (layout snapshots, launcher history, welcome-done flag) |

The development install adds no autostart entry. The Welcome tour starts
automatically only from the package (`/etc/xdg/autostart`), and only once
per user.

## Wallpapers

The wallpapers are procedural: `jeronix_design.py` draws nested J contours
from the token palette and composes each one for its own resolution, so
nothing is cropped. The build renders 1920x1080, 2560x1440, 2560x1600 and
3840x2160 for both modes, plus 4K vector SVGs. To add a size, extend
`WALLPAPER_SIZES` in `scripts/jeronix_design.py`.
