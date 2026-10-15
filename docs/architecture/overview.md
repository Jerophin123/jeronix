# Architecture overview

JERONIX is Ubuntu 26.04 LTS plus a JERONIX layer of desktop styling,
extensions and applications. GNOME Shell and Mutter remain the desktop
infrastructure; JERONIX never replaces the shell or window manager.

## Layers

| Layer | Contents | Lives in |
| --- | --- | --- |
| A. Linux base | Kernel, systemd, APT, drivers, security updates (all Ubuntu-provided) | `system/` (defaults only) |
| B. GNOME platform | Shell, Mutter, GDM, GTK 4, libadwaita (Ubuntu-provided, unmodified) | n/a |
| C. JERONIX desktop | Shell theme, extensions, icons, wallpapers, layouts, session defaults | `desktop/` |
| D. JERONIX apps | Welcome, Layout Studio, Settings, System Information | `apps/` |
| E. Packaging | Debian packages, manifests | `packaging/` |
| F. Image and release | ISO build, installer config, checksums, VM tests | `build/` |

Supporting directories:

- `design/`: tokens, artwork and guidelines, consumed by C and D.
- `config/platform.json`: supported platform versions, consumed by tests and
  packaging.
- `tests/` and `scripts/`.

## Boundary rules

- Layers C and D may read `design/` and `config/`. They must not import
  anything from `build/` or `packaging/`.
- Layer F installs packages produced by E. It contains no application logic.
- Nothing in C or D needs root. Layouts are data (validated JSON/GSettings
  values), never shell code.
- GNOME system files under `/usr/share/gnome-shell` are never edited.
  Customization goes through extensions, GSettings overrides and themes.

## Extension conventions

- One directory per extension in `desktop/extensions/<name>/`, with UUID
  `<name>@jeronix`.
- ES modules only, with a default-exported `Extension` subclass.
- `enable()` creates everything and `disable()` destroys everything. No
  state is kept across `disable()`.
- Logic that doesn't need Shell imports lives in its own module so `gjs` can
  unit-test it outside the shell.
- Every extension needs a headless lifecycle test before it is enabled by
  default.

See [decisions/](decisions/) for recorded architecture decisions.
