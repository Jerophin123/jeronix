# JERONIX

A handcrafted, customizable Linux distribution built on Ubuntu 26.04 LTS and
GNOME 50.

> **Status: early development (Milestones 1–4 plus a first ISO builder).**
> `scripts/build-iso.sh` produces a JERONIX ISO by remastering Ubuntu
> 26.04.1 Desktop. Boot and installation of that ISO still have to be
> verified in clean VMs ([docs/development/iso-testing.md](docs/development/iso-testing.md)).
> Until then, nothing here should be described as a usable distribution.

## What works today

| Component | State | Verified by |
| --- | --- | --- |
| Platform baseline ([config/platform.json](config/platform.json)) | Ubuntu 26.04, GNOME Shell 50 | Environment audit |
| Design tokens ([design/tokens/tokens.json](design/tokens/tokens.json)) | Palettes, panel, interaction states, type, spacing, components, elevation, motion | Unit tests (structure, WCAG contrast) |
| Logo family ([design/icons/](design/icons/README.md)) | Mark v0.2, small and symbolic icons, glyphs, wordmark, lockups, boot art | SVG validity and rendering tests |
| Wallpapers | Procedural dark and light, 1080p to 4K | Rendering and palette tests |
| `jeronix-shell-theme` extension | Generated GNOME Shell stylesheet (dark + light) | Unit tests and headless GNOME Shell computed-style test |
| Pure layout ([desktop/layouts/pure.json](desktop/layouts/pure.json)) | Validated GSettings layout with snapshot and restore | Sandboxed apply/restore tests |
| `jeronix-quick-settings` extension | Stay Awake toggle | Unit tests and headless GNOME Shell lifecycle test |
| `jeronix-desktop` package ([packaging/](packaging/jeronix_payload.py)) | All of the above plus Pure as dconf system defaults | Payload and .deb tests |
| ISO builder ([build/iso/](build/iso/README.md)) | Verified Ubuntu 26.04.1 source, rebuilt base layer, unchanged signed boot chain | Builder tests and image validation; boot test pending |

The Milestone 4 visuals have been checked automatically, but not yet in a
live session. See [docs/development/milestone-4.md](docs/development/milestone-4.md).

## Repository map

```
config/      supported platform versions
design/      tokens, logo and icons, design guidelines
desktop/     shell theme, extensions, layouts, session defaults
apps/        native GTK 4 / libadwaita applications (planned)
packaging/   Debian packaging (planned)
build/       ISO and release engineering (planned)
docs/        architecture, ADRs, development notes
scripts/     developer tooling
tests/       unit and integration tests
```

## Development

Requirements: Ubuntu 26.04 with GNOME Shell 50, `gjs` and `python3-gi`.
These are present on a default desktop install.

```sh
scripts/run-tests.sh            # everything
scripts/run-tests.sh unit       # fast: tokens, manifests, JS syntax, gjs unit tests
scripts/run-tests.sh integration  # isolated headless GNOME Shell lifecycle and theme tests
scripts/jeronix_design.py build   # derived theme, wallpapers and icons into out/
scripts/install-desktop-dev.sh    # user-level install of the desktop identity (switches nothing on)
scripts/build-iso.sh              # out/iso/jeronix-26.04-x86_64.iso (needs xorriso, ~25 GiB scratch)
```

None of the tests need root, and none touch the running desktop session.
To try the theme and the Pure layout, and to undo them, see
[docs/development/desktop-identity.md](docs/development/desktop-identity.md).

See [docs/development/environment-audit.md](docs/development/environment-audit.md)
for the verified platform and roadmap, and
[docs/architecture/overview.md](docs/architecture/overview.md) for the
design.

## License

Code: GPL-3.0-or-later ([LICENSE](LICENSE)). Artwork in `design/`:
CC-BY-SA-4.0.
