# ADR 0001: Platform and testing baseline

Status: accepted (2026-10-15)

## Context

JERONIX targets Ubuntu 26.04 LTS. The development VM was verified to run
Ubuntu 26.04.1 with GNOME Shell 50.1 on Wayland. GNOME 50 has no X11
session, and shell restarts are no longer possible in place, so extension
work can't be tested quickly in the live session.

## Decision

1. Supported versions live only in `config/platform.json`. Extension
   `shell-version` arrays must equal `gnome_shell.supported_versions`
   (enforced by `tests/unit/test_extensions.py`).
2. Extension lifecycle is tested in an **isolated headless GNOME Shell**:
   `dbus-run-session`, a temporary HOME/XDG tree, in-memory GSettings and a
   virtual monitor. External services the extension uses are replaced by
   fakes on the private bus.
3. Tests that need the shell's internals use a **test-only probe
   extension** (`tests/integration/probe-extension`), which is never
   packaged.
4. Code is licensed GPL-3.0-or-later, the usual license for GNOME Shell
   extensions and compatible with GNOME Shell's GPL-2.0-or-later. Artwork is
   CC-BY-SA-4.0.

## Consequences

- Lifecycle tests run without root, a display or logging out, and don't
  touch the user's desktop or dconf settings.
- Supporting a new GNOME release means updating `config/platform.json`,
  updating the manifests and re-running the headless tests on that release.
- Visual and interaction checks still need a manual session test after a
  logout, or `gnome-shell --devkit` (package `mutter-dev-bin`).
