# ADR 0002: Shell theme delivery and declarative layouts

Status: accepted (2026-10-15)

## Context

Milestone 4 needs a JERONIX look for GNOME Shell 50.1 on Ubuntu 26.04 and a
first layout (Pure), without root and without editing system files.
Inspecting the VM established these facts:

- Ubuntu's `ubuntu` session mode sets `Yaru/gnome-shell.css` as the default
  stylesheet and enables seven mode extensions (`ubuntu-dock`, `ding` and
  others) through the session mode, not through `enabled-extensions`.
- The `user-theme` extension (`gnome-shell-extensions`) is **not
  installed**, and installing it needs root. It also replaces the default
  stylesheet entirely.
- GNOME Shell 50 loads `<mode>-<variant>.css`, then `stylesheet-<variant>.css`,
  then `stylesheet.css` from an enabled extension, swaps the file when the
  color scheme changes and unloads it on disable
  (`js/ui/extensionSystem.js`).
- Yaru marks the panel background and all focus rings `!important`.
- Ubuntu maps the GNOME `accent-color` value `slate` to its Yaru sage variant.

## Decision

1. **The shell theme is a stylesheet-only extension**
   (`jeronix-shell-theme@jeronix`). Its CSS overrides only the properties
   JERONIX changes, on top of the default theme. It uses `!important` only
   where Yaru does.
2. **The CSS is generated** from `design/tokens/tokens.json` and one
   template (`desktop/theme/gnome-shell/jeronix.css.in`) by
   `scripts/jeronix_design.py`, which also produces wallpapers and icon
   renders. Generated files go to `out/` and are never committed. Derived
   colors (hover, pressed) are computed in Python rather than with St's
   `st-mix()`, so their contrast can be tested.
3. **The theme is verified in a real shell.** `tests/integration/theme_lifecycle.py`
   runs a headless GNOME Shell in the `ubuntu` session mode (Yaru
   underneath) and compares computed styles with token values in both
   color schemes.
4. **Layouts are allowlisted GSettings data.** `scripts/jeronix_layout.py`
   checks each value against the installed schema, saves a snapshot before
   writing and restores it on request. Layouts never enable or disable
   extensions, and they can't run commands.
5. **Pure reconfigures Ubuntu's dock and desktop icons instead of removing
   them**, so there is never a second dock and no extension state is touched.

## Consequences

- Rollback is immediate: disabling the extension restores Yaru without a
  logout, and `restore` undoes a layout.
- The theme depends on GNOME 50 class names. Each new GNOME release must
  re-run `theme_lifecycle.py`; a selector rename shows up as a mismatch.
- Things CSS cannot do (panel layout, overview structure, dock removal) need
  extensions or Layout Studio (Milestone 5).
- Boot (Plymouth) and login (GDM) branding are system-wide, so they ship
  with the packages (Milestone 7). Milestone 4 provides only the assets.
- The headless test can't judge visual quality. A manual session check is
  still required (see `docs/development/desktop-identity.md`).
