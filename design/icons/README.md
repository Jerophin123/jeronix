# JERONIX logo and icon assets

All files here are original JERONIX artwork (CC-BY-SA-4.0), hand-authored
SVG with colors taken only from [../tokens/tokens.json](../tokens/tokens.json).
They contain no fonts, embedded images or scripts, so they render the same
everywhere. The wordmark letters are drawn strokes rather than text.

## The mark

A drawn **J**: a vertical stem that curves into an open bowl and hooks back
upward, with an offset **seed** dot standing in for the crossbar. The stem
is sage, the seed is light sage, and the tile is charcoal.

v0.2 (Milestone 4) refined the v0.1 draft:

- The J is now a filled outline rather than a stroke, so it renders the same
  in every tool and can serve as a symbolic icon.
- The glyph is optically centered on the tile. It sits slightly right of
  center, because the stem carries most of its weight.
- A separate small-size master keeps the counter open at 16 and 24 px.

The v0.1 draft is kept unchanged in [archive/jeronix-mark-v0.1.svg](archive/jeronix-mark-v0.1.svg),
and its history is in Git.

## Files

| File | Size (viewBox) | Background | Use |
| --- | --- | --- | --- |
| `jeronix-mark.svg` | 128x128 | any (own tile) | App and system identity at 32 px and up; source for the hicolor PNGs |
| `jeronix-mark-small.svg` | 16x16 | any (own tile) | Small-size master for the 16 and 24 px icons: thicker J, bigger seed |
| `jeronix-mark-symbolic.svg` | 16x16 | any (recolored) | Symbolic icon for panels, menus and settings, with fills only |
| `jeronix-glyph-on-dark.svg` | 128x128 | dark, transparent | The J without its tile, for dark surfaces |
| `jeronix-glyph-on-light.svg` | 128x128 | light, transparent | The J without its tile, for light surfaces (moss) |
| `jeronix-wordmark-on-dark.svg` | 242x56 | dark, transparent | Wordmark, light text; login screen logo |
| `jeronix-wordmark-on-light.svg` | 242x56 | light, transparent | Wordmark, dark text |
| `jeronix-lockup-on-dark.svg` | 424x128 | dark, transparent | Mark plus wordmark: Welcome app header, about dialogs |
| `jeronix-lockup-on-light.svg` | 424x128 | light, transparent | Same, for light mode |
| `jeronix-boot.svg` | 256x184 | black, transparent | Stacked glyph and wordmark for boot (Plymouth) and login splash |

Minimum sizes: use the mark at 16 px or larger, the wordmark at least 80 px
wide, and the lockup at least 160 px wide. Keep clear space of at least the
seed's diameter around every asset.

## Rendered outputs

`scripts/jeronix_design.py build` renders PNGs into `out/`, which is not
committed:

| Output | Pixels | From |
| --- | --- | --- |
| `icons/hicolor/{16,24}x…/apps/jeronix.png` | 16, 24 | `jeronix-mark-small.svg` |
| `icons/hicolor/{32…512}x…/apps/jeronix.png` | 32, 48, 64, 128, 256, 512 | `jeronix-mark.svg` |
| `icons/hicolor/scalable/apps/jeronix.svg` | vector | `jeronix-mark.svg` |
| `icons/hicolor/symbolic/apps/jeronix-symbolic.svg` | vector | `jeronix-mark-symbolic.svg` |
| `branding/jeronix-boot.png`, `@2x` | 256x184, 512x368 | `jeronix-boot.svg` |
| `branding/jeronix-login-logo.png`, `@2x` | 242x56, 484x112 | `jeronix-wordmark-on-dark.svg` |
| `branding/jeronix-welcome-on-{dark,light}.png` | 848x256 | lockups |

Icon sizes come from `icon-size-px` in the tokens.

## Boot and login

The boot and login assets are ready, but they are **not installed** in this
milestone. Both destinations are system-wide and need root:

- **Plymouth** reads PNGs from a theme in `/usr/share/plymouth/themes/`.
  Ubuntu's `bgrt` and `spinner` themes take a `watermark.png`, so
  `branding/jeronix-boot.png` (or `@2x` on HiDPI) is that watermark.
- **GDM** takes a logo via the dconf key `org/gnome/login-screen/logo` in the
  `gdm` dconf database. Use `branding/jeronix-login-logo.png`.

Both will be shipped by the Debian packages (Milestone 7) and tested in a
disposable VM. Don't install them by hand on the development VM.
