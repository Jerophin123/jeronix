# Desktop identity: install, test and roll back

This covers the Milestone 4 pieces: the shell theme, wallpapers, icons and
the Pure layout. Everything installs for the current user only. No root, no
system files and no change to the GNOME session, GDM or system theme.

## What changes when

| Step | Command | Effect | Logout needed? |
| --- | --- | --- | --- |
| Build | `scripts/jeronix_design.py build` | Writes derived assets to `out/` only | No |
| Install | `scripts/install-desktop-dev.sh` | Copies the theme extension, wallpapers and icons into `~/.local/share`. Nothing is switched on | **Once**, the first time, so GNOME Shell discovers the new extension (Wayland can't rescan in place) |
| Theme on | `gnome-extensions enable jeronix-shell-theme@jeronix` | Loads the JERONIX stylesheet live | No |
| Theme off | `gnome-extensions disable jeronix-shell-theme@jeronix` | Back to the default theme instantly | No |
| Reinstall after changing tokens | `scripts/install-desktop-dev.sh`, then disable and enable the theme | Loads the new stylesheet | Normally no. If the old look persists, log out and back in |
| Layout preview | `scripts/jeronix_layout.py plan desktop/layouts/pure.json` | Lists what would change. Writes nothing | No |
| Layout on | `scripts/jeronix_layout.py apply desktop/layouts/pure.json` | Saves a snapshot, then sets the GSettings values | No. Settings apply live |
| Layout off | `scripts/jeronix_layout.py restore` | Restores the latest snapshot | No |
| Uninstall | `scripts/install-desktop-dev.sh --remove` | Disables the theme and deletes exactly the installed files | No |

## Manual test in a real GNOME Wayland session

These steps are for a person at the VM's desktop. They have **not been
performed yet** for Milestone 4; only the automated headless checks have run.

1. `scripts/run-tests.sh` passes.
2. `scripts/install-desktop-dev.sh`, then log out and back in.
3. `gnome-extensions info jeronix-shell-theme@jeronix` shows state
   `INITIALIZED` or `INACTIVE`.
4. `gnome-extensions enable jeronix-shell-theme@jeronix`, then check:
   - The top panel is charcoal and panel buttons have pill-shaped hover.
   - Quick Settings: the toggles are charcoal, and toggles that are on are
     sage with dark text. **Stay Awake still works** (with it on,
     `gnome-session-inhibit --list` shows it).
   - Popover menus, the calendar and notifications use the JERONIX surfaces.
   - `Super`: in the overview and search, hover and selection are sage-tinted.
   - Keyboard only: `Super`, type, then use the arrows and `Tab`. Every
     focused item has a clear ring. `Super+S` opens Quick Settings, and
     `Tab` moves through the toggles.
5. Settings → Appearance → Style: switch Light/Dark. The shell follows
   without a logout.
6. `scripts/jeronix_layout.py plan desktop/layouts/pure.json`, then `apply`.
   Check: the wallpaper changes, the dock hides until needed, the desktop
   icons are gone, the clock shows the weekday, and the title bars show only
   close.
7. `scripts/jeronix_layout.py restore`. Every setting is back as before.
8. `gnome-extensions disable jeronix-shell-theme@jeronix`. Yaru is back.
9. `scripts/install-desktop-dev.sh --remove`.

Record the results (with screenshots if possible) in the milestone notes
before calling the manual test complete.

## Rolling back

**The theme looks wrong or unreadable:**

- Run `gnome-extensions disable jeronix-shell-theme@jeronix` in a terminal
  (`Ctrl+Alt+T`), or switch it off in the Extensions app. It takes effect
  immediately.
- If the shell is unusable, open a text console with `Ctrl+Alt+F3`, log in
  and run:

  ```sh
  rm -rf ~/.local/share/gnome-shell/extensions/jeronix-shell-theme@jeronix
  ```

  Then go back with `Ctrl+Alt+F2` (or reboot) and log in again. A
  missing extension is simply skipped.
- Last resort, no files touched: on the login screen you can't toggle
  extensions, but from the text console,
  `dbus-run-session gsettings set org.gnome.shell disable-user-extensions true`
  turns off **all** user extensions at the next login. Undo it later with
  `gsettings reset org.gnome.shell disable-user-extensions`.

**The layout changed something you want back:**

- `scripts/jeronix_layout.py restore` restores the most recent snapshot.
- `scripts/jeronix_layout.py snapshots` lists every snapshot (in
  `~/.local/state/jeronix/layout-snapshots/`). Pass a path to `restore` to
  go back further.
- Keys that were at their default before `apply` are reset, not written, so
  later system default changes still reach you.
- Without the tool, `gsettings reset <schema> <key>` resets any single key.
  The keys are listed in [desktop/layouts/README.md](../../desktop/layouts/README.md).

**Remove everything:** `scripts/jeronix_layout.py restore`, then
`scripts/install-desktop-dev.sh --remove`. The uninstaller refuses to run
while a JERONIX wallpaper is still set, so you're never left with a missing
wallpaper. `--force` overrides that.

## Where things go

| Item | Location |
| --- | --- |
| Source tokens, template, SVGs, layout | the repository |
| Generated assets | `out/` (Git-ignored), or a temporary directory during install |
| Theme extension | `~/.local/share/gnome-shell/extensions/jeronix-shell-theme@jeronix/` |
| Wallpapers | `~/.local/share/backgrounds/jeronix/` plus `~/.local/share/gnome-background-properties/jeronix.xml` (adds them to Settings → Appearance) |
| Icons | `~/.local/share/icons/hicolor/*/apps/jeronix*.{png,svg}` |
| Install record | `~/.local/share/jeronix/dev-install.manifest` |
| Layout snapshots (runtime state) | `~/.local/state/jeronix/layout-snapshots/` |

## Wallpapers

The wallpapers are procedural: `jeronix_design.py` draws nested J contours
from the token palette and composes each one for its own resolution, so
nothing is cropped. The build renders 1920x1080, 2560x1440, 2560x1600 and
3840x2160 for both modes (about 3 MB in total), plus 4K vector SVGs. The
installer uses the 3840x2160 PNG, and GNOME scales it down. To add a size,
extend `WALLPAPER_SIZES` in `scripts/jeronix_design.py`.
