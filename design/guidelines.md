# JERONIX design guidelines (v0.1)

All values come from [tokens/tokens.json](tokens/tokens.json). Code and
artwork reference token names, never raw values.

## Character

Calm, premium and handcrafted. Charcoal surfaces, muted sage accents,
generous spacing, rounded shapes and restrained motion.

## Color

- Both dark and light modes define the same roles (`surface`, `text`,
  `accent`, `on-accent` and so on). Tests enforce this.
- Contrast minimums (WCAG 2.x) are listed in `contrast.pairs` and checked
  for both modes: 4.5:1 for text, 3:1 for focus rings and non-text UI.
- Never use the accent as the only signal of state. Pair it with an icon,
  label or shape.

## Typography

Ubuntu Sans for UI text and Ubuntu Sans Mono for code. Both ship with
Ubuntu 26.04, so no fonts are bundled. Sizes are multiples of
`base-size-pt` taken from `typography.scale`, so the user's font scaling
applies to all of them.

## Shape, spacing, elevation

- Spacing uses only the steps in `spacing-px` (a 4 px grid).
- Radius: `small` for controls, `medium` for cards and popovers, `large` for
  dialogs and the dock, `pill` for toggles.
- Use the two shadow levels only: `raised` and `overlay`.

## Motion

Use 120 ms for feedback, 200 ms for transitions and 320 ms for large
surfaces, with ease-out-quad easing. When the system's reduced-motion
setting (`org.gnome.desktop.interface enable-animations`) is off, use 0 ms.

## Keyboard and accessibility

- Every interactive element must be reachable and operable from the
  keyboard, with a visible `focus-ring`.
- Every control needs an accessible name. Shell toggles inherit theirs from
  `title`.
- Icon-only buttons need tooltips.

## Logo

`icons/jeronix-mark.svg` is a drawn J: a stem that hooks back upward, plus
an offset "seed" dot in place of the crossbar, on a charcoal tile. It is an
**initial draft**. Monochrome, boot, login and installer variants are
planned for Milestone 4. Brand colors come from the `brand` tokens.
