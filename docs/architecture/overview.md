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
- Source and derived files are kept apart. Generated stylesheets, wallpaper
  renders and icon PNGs go to `out/` (never committed); runtime state such
  as layout snapshots goes to `$XDG_STATE_HOME/jeronix/`.

## Desktop identity pipeline (Milestone 4)

```
design/tokens/tokens.json ─┐
desktop/theme/gnome-shell/ ├─ scripts/jeronix_design.py build ─► out/
  jeronix.css.in           │     extensions/jeronix-shell-theme@jeronix/stylesheet-{dark,light}.css
design/icons/*.svg ────────┘     wallpapers/  icons/hicolor/  branding/

out/ ─ scripts/install-desktop-dev.sh ─► ~/.local/share (theme, wallpapers, icons; nothing enabled)
desktop/layouts/pure.json ─ scripts/jeronix_layout.py apply|restore ─► GSettings (+ snapshot)
```

- The shell theme is a stylesheet-only extension layered over the session's
  default theme (Yaru), as decided in
  [ADR 0002](decisions/0002-shell-theme-and-layouts.md).
- Layouts are allowlisted GSettings values checked against the installed
  schemas. They never toggle extensions.

## Packaging and image (first iteration)

```
repo ─ packaging/jeronix_payload.py ─► jeronix-desktop tree + .deb
          (extensions, wallpapers, icons, layout tool, Pure as dconf system db)

official Ubuntu 26.04.1 ISO (signed SHA256SUMS) ─┐
jeronix-desktop tree ───────────────────────────┼─ build/iso/jeronix_iso.py ─► out/iso/jeronix-26.04-x86_64.iso
                                                 │    rebuild casper/minimal.squashfs (no root)
                                                 └─   xorriso replay of Ubuntu's signed boot setup
```

See [ADR 0003](decisions/0003-iso-remastering.md) and
[build/iso/README.md](../../build/iso/README.md). The `.deb` is a
first-step package. Source packages and an APT repository remain M7 work.

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
