# SPDX-License-Identifier: GPL-3.0-or-later
"""Display configuration for JERONIX Settings, as plain data.

Reads the reply of Mutter's org.gnome.Mutter.DisplayConfig.GetCurrentState
and builds the arguments of ApplyMonitorsConfig. No D-Bus or GTK here, so
it is unit-tested with fixtures (tests/unit/test_settings.py).

Mutter accepts only arrangements without gaps or overlaps, so enabled
displays are laid out side by side, left to right in the user's order, top
edges aligned. In the logical layout mode positions are in scaled pixels;
in the physical mode in device pixels.
"""

from dataclasses import dataclass, field

LAYOUT_LOGICAL, LAYOUT_PHYSICAL = 1, 2
METHOD_VERIFY, METHOD_TEMPORARY, METHOD_PERSISTENT = 0, 1, 2
# wl_output transforms: 0 normal, 1 90°, 2 180°, 3 270° (+4 flipped).
ROTATIONS = ((0, "Normal"), (1, "90° (left)"), (3, "90° (right)"), (2, "Upside down"))


@dataclass
class Mode:
    id: str
    width: int
    height: int
    rate: float
    preferred_scale: float
    scales: list
    current: bool = False
    preferred: bool = False

    @property
    def resolution(self):
        return (self.width, self.height)


@dataclass
class Monitor:
    connector: str
    name: str
    builtin: bool
    modes: list
    enabled: bool = False
    x: int = 0
    y: int = 0
    scale: float = 1.0
    transform: int = 0
    primary: bool = False
    mode_id: str = None
    spec: tuple = field(default=())

    @property
    def mode(self):
        return next((m for m in self.modes if m.id == self.mode_id), None)

    def resolutions(self):
        """Distinct resolutions, largest first."""
        seen = []
        for m in sorted(self.modes, key=lambda m: (-m.width * m.height, -m.width)):
            if m.resolution not in seen:
                seen.append(m.resolution)
        return seen

    def rates(self, resolution):
        """Modes of one resolution, fastest first."""
        return sorted((m for m in self.modes if m.resolution == resolution), key=lambda m: -m.rate)


def parse_state(state):
    """(serial, [Monitor], layout_mode) from GetCurrentState's unpacked reply."""
    serial, monitors, logical, props = state
    result = {}
    order = []
    for spec, modes, mprops in monitors:
        connector = spec[0]
        parsed = [Mode(id=m[0], width=m[1], height=m[2], rate=m[3], preferred_scale=m[4], scales=list(m[5]),
                       current=bool(m[6].get("is-current")), preferred=bool(m[6].get("is-preferred")))
                  for m in modes]
        current = next((m for m in parsed if m.current), None)
        result[connector] = Monitor(connector=connector, name=mprops.get("display-name") or connector,
                                    builtin=bool(mprops.get("is-builtin")), modes=parsed,
                                    mode_id=current.id if current else None, spec=tuple(spec))
        order.append(connector)
    for x, y, scale, transform, primary, specs, _ in logical:
        for spec in specs:
            m = result.get(spec[0])
            if m:
                m.enabled, m.x, m.y, m.scale, m.transform, m.primary = True, x, y, scale, transform, primary
    for m in result.values():
        if m.enabled and m.mode_id is None:
            preferred = next((md for md in m.modes if md.preferred), m.modes[0] if m.modes else None)
            m.mode_id = preferred.id if preferred else None
    # Left to right, as they are arranged now; disabled displays last.
    ordered = sorted((result[c] for c in order), key=lambda m: (not m.enabled, m.x, m.y))
    return serial, ordered, int(props.get("layout-mode", LAYOUT_LOGICAL))


def nearest_scale(mode, scale):
    """The supported scale of mode closest to scale."""
    if not mode.scales:
        return 1.0
    return min(mode.scales, key=lambda s: abs(s - scale))


def footprint(monitor, layout_mode):
    """(width, height) the monitor occupies in the layout's coordinates."""
    mode = monitor.mode
    w, h = mode.width, mode.height
    if monitor.transform % 2 == 1:  # rotated by 90° or 270°
        w, h = h, w
    if layout_mode == LAYOUT_LOGICAL:
        return round(w / monitor.scale), round(h / monitor.scale)
    return w, h


def problems(monitors):
    """Why this configuration cannot be applied ([] if it can)."""
    enabled = [m for m in monitors if m.enabled]
    found = []
    if not enabled:
        found.append("At least one display must stay on.")
    if sum(1 for m in enabled if m.primary) != 1:
        found.append("Exactly one display must be the primary display.")
    for m in enabled:
        if m.mode is None:
            found.append(f"{m.name} has no resolution.")
        elif m.scale not in m.mode.scales:
            found.append(f"{m.name} does not support {m.scale:g}x at {m.mode.width}x{m.mode.height}.")
    return found


def arrange(monitors, layout_mode):
    """Places enabled monitors side by side in list order (no gaps or
    overlaps, top edges at 0); returns the same list."""
    x = 0
    for m in monitors:
        if not m.enabled:
            continue
        m.x, m.y = x, 0
        x += footprint(m, layout_mode)[0]
    return monitors


def apply_arguments(serial, monitors, layout_mode, method=METHOD_PERSISTENT):
    """The (serial, method, logical_monitors, properties) tuple for
    ApplyMonitorsConfig, after arranging the monitors."""
    found = problems(monitors)
    if found:
        raise ValueError(" ".join(found))
    arrange(monitors, layout_mode)
    logical = [(m.x, m.y, float(m.scale), m.transform, m.primary, [(m.connector, m.mode_id, {})])
               for m in monitors if m.enabled]
    return (serial, method, logical, {"layout-mode": layout_mode})


def mode_label(mode):
    return f"{mode.width} × {mode.height}"


def rate_label(mode):
    return f"{mode.rate:.2f} Hz"


def scale_label(scale):
    return f"{round(scale * 100)} %"
