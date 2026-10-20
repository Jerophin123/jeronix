# Fluent UI System Icons (status icons)

The symbolic icons of the JERONIX system tray and Quick Settings (network,
sound, power, battery, Bluetooth, and the other indicators) are Microsoft's
[Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons),
the set Windows 11 uses, to match the Windows 11-style taskbar.

- Source: `assets/<Icon>/SVG/ic_fluent_<icon>_16_regular.svg` (or `_20_`
  where there is no 16 px drawing), at commit
  `83b26348c811f072429427ff48362238656524fe`.
- License: MIT, Copyright (c) 2020 Microsoft Corporation (see `LICENSE`).
- Each file keeps only the icon's path data: no colors, styles or anything
  else from the original. `scripts/jeronix_icons.py` maps them to GNOME's
  icon names (`STATUS_ICONS`) and writes them, in one ink, into the
  JERONIX icon theme under `scalable/status`.

To add an icon, download its regular SVG from the same commit, keep only
its `<path>` elements and the `viewBox`, save it here under the Fluent name
(for example `wifi_1.svg`), and map it in `STATUS_ICONS`.
