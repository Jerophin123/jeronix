# JERONIX

A handcrafted, customizable Linux distribution built on Ubuntu 26.04 LTS and
GNOME 50.

> **Status: early development (Milestones 1–3).** There is no ISO or
> installer yet. Nothing here should be described as a usable distribution
> until boot and installation have been verified in clean VMs.

## What works today

| Component | State | Verified by |
| --- | --- | --- |
| Platform baseline ([config/platform.json](config/platform.json)) | Ubuntu 26.04, GNOME Shell 50 | Environment audit |
| Design tokens ([design/tokens/tokens.json](design/tokens/tokens.json)) | Dark and light palettes, type, spacing, motion | Unit tests (WCAG contrast) |
| Logo mark ([design/icons/jeronix-mark.svg](design/icons/jeronix-mark.svg)) | First draft | Token-color test |
| `jeronix-quick-settings` extension | Stay Awake toggle | Unit tests and headless GNOME Shell lifecycle test |

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
scripts/run-tests.sh integration  # isolated headless GNOME Shell lifecycle test
```

None of the tests need root, and none touch the running desktop session.

See [docs/development/environment-audit.md](docs/development/environment-audit.md)
for the verified platform and roadmap, and
[docs/architecture/overview.md](docs/architecture/overview.md) for the
design.

## License

Code: GPL-3.0-or-later ([LICENSE](LICENSE)). Artwork in `design/`:
CC-BY-SA-4.0.
