# JERONIX Shell Theme

UUID: `jeronix-shell-theme@jeronix`. Supports GNOME Shell 50.

A stylesheet-only extension. When it is enabled, GNOME Shell loads
`stylesheet-dark.css` or `stylesheet-light.css` from the extension directory,
following the system color scheme, on top of the session's default theme
(Yaru on Ubuntu). Disabling it unloads the stylesheet immediately. No
logout is needed, and no other extension or setting is affected.

The stylesheets are **generated**: run `scripts/jeronix_design.py build` to
create them from [design/tokens/tokens.json](../../../design/tokens/tokens.json)
and the template
[desktop/theme/gnome-shell/jeronix.css.in](../../theme/gnome-shell/jeronix.css.in).
They are not in this source directory. Install the extension with
`scripts/install-desktop-dev.sh`, not `install-extension-dev.sh`.

## What it styles

Top panel and panel buttons; popover menus; Quick Settings toggles, menus
and sliders; app grid and search tiles; the search entry and results;
notifications, the message list and calendar; switchers, OSDs and modal
dialogs; and keyboard focus rings everywhere.

## Why an extension and not a shell theme

GNOME Shell offers no supported way to load a user shell theme without the
`user-theme` extension. That extension is not installed on Ubuntu 26.04
(it would need root), and it replaces the whole session theme, so a
complete stylesheet would be required. An extension stylesheet layers only
what JERONIX changes over the maintained default theme, and it can be
undone instantly. See
[ADR 0002](../../../docs/architecture/decisions/0002-shell-theme-and-layouts.md).

## Tests

```sh
python3 -m unittest discover -s tests/unit -p test_theme.py   # generation, colors, contrast, focus rings
python3 tests/integration/theme_lifecycle.py                   # computed styles in a real headless shell
```
