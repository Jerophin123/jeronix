# Milestone 4: desktop identity

Status: **implemented and automatically verified (2026-10-15). Manual
session test pending.**

Target: Ubuntu 26.04.1, GNOME Shell and Mutter 50.1 (Wayland), GJS 1.88.

## Delivered

| Deliverable | Where |
| --- | --- |
| Design tokens 0.2.0: panel, text-secondary, interaction states, components, elevation, wallpaper palette, brand contrast | [design/tokens/tokens.json](../../design/tokens/tokens.json), [design/guidelines.md](../../design/guidelines.md) |
| Asset generator (theme, wallpapers, icon and branding PNGs) | [scripts/jeronix_design.py](../../scripts/jeronix_design.py) |
| GNOME Shell theme (dark and light), as a stylesheet-only extension | [desktop/theme/gnome-shell/jeronix.css.in](../../desktop/theme/gnome-shell/jeronix.css.in), [desktop/extensions/jeronix-shell-theme/](../../desktop/extensions/jeronix-shell-theme/README.md) |
| Logo v0.2 and its variants (v0.1 archived) | [design/icons/](../../design/icons/README.md) |
| Procedural wallpapers, dark and light, from 1080p to 4K | `scripts/jeronix_design.py build` into `out/wallpapers/` |
| Pure layout, plus a validating apply/restore tool | [desktop/layouts/](../../desktop/layouts/README.md), [scripts/jeronix_layout.py](../../scripts/jeronix_layout.py) |
| Development install and removal | [scripts/install-desktop-dev.sh](../../scripts/install-desktop-dev.sh), [desktop-identity.md](desktop-identity.md) |
| Architecture decision | [ADR 0002](../architecture/decisions/0002-shell-theme-and-layouts.md) |

## Verification

`scripts/run-tests.sh all` on the development VM. This was run twice in a
row and passed both times, finishing in about 20 s:

| Suite | Result |
| --- | --- |
| Token check (`jeronix_design.py check`): 43 contrast pairs | all pass |
| Python unit tests: tokens, theme, branding, wallpapers, layout, dev install, docs, extension manifests | 60 run, 0 skipped, all pass |
| gjs unit tests (Stay Awake inhibitor) | 8 pass |
| Headless lifecycle test for `jeronix-quick-settings` (Stay Awake) | 32 checks pass, unchanged from Milestone 3 |
| Headless theme test in session mode `ubuntu` over Yaru: 14 computed styles × 2 color schemes, variant switching, clean disable | 9 checks pass |

A mutation check was also run. Breaking the `.search-entry` rule in the
template made the theme test fail with the Yaru color, which shows that the
test detects regressions.

After the tests, the real user session was checked. Settings were
unchanged, no extensions were installed, there was no JERONIX state and no
temporary directories were left behind.

**Not yet done:** a visual and interaction check in a live GNOME Wayland
session on the VM. The procedure is in
[desktop-identity.md](desktop-identity.md#manual-test-in-a-real-gnome-wayland-session).

## Known GNOME 50.1 limitations

- **No user shell theme without `user-theme`.** That extension isn't
  installed on Ubuntu 26.04 and would replace Yaru entirely. JERONIX
  therefore layers an extension stylesheet over Yaru (ADR 0002). Anything
  Yaru styles that the template doesn't override keeps Yaru's look.
- **`-st-accent-color` can't be redefined from CSS.** Widgets that the
  template doesn't restyle still use the system accent. Pure sets
  `accent-color` to `slate`, which Ubuntu renders as Yaru sage, so those
  widgets stay in the same color family.
- **New extensions need one logout on Wayland** before GNOME Shell can see
  them. After that, enable and disable work live.
- **CSS cannot change structure.** Panel item order, the overview layout and
  dock presence need code. Pure only reconfigures Ubuntu's dock and desktop
  icons; it doesn't disable them, because that would mean touching the
  enabled-extensions list.
- **Boot and login branding need root.** Plymouth and GDM assets are
  produced but not installed. They're planned for packaging in M7.
- **The headless shell has no GPU or blur.** The tests check resolved
  styles, not rendered pixels.

## Next: Milestone 5 (layout engine and Layout Studio)

Builds on the layout format and the snapshot and restore tool from this
milestone:

- More presets (Classic and Studio). These need the planned `jeronix-dock`
  extension.
- Explicit, reversible switching of `ubuntu-dock` and `ding`, recorded in
  snapshots.
- A Layout Studio GTK 4 / libadwaita app with preview and rollback.

Outstanding dependencies:

- The manual session test above. Someone has to do it at the VM desktop.
- Optional: `mutter-dev-bin` for `gnome-shell --devkit` visual testing
  without logging out (needs sudo).
- Optional: `shellcheck` for linting the shell scripts.
