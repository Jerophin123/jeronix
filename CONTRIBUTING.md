# Contributing

## Workflow

1. Check `git status` before editing, and keep unrelated changes out of
   your commits.
2. Make the smallest change that delivers working behavior, and add or
   update its tests.
3. Run `scripts/run-tests.sh`. Report results honestly: a test that was
   skipped or not run is not a pass.
4. Update the docs that describe the behavior you changed.

## Rules

- Never commit passwords, tokens, keys, ISOs or disk images (see
  `.gitignore`).
- Desktop components and apps must work without root. Privileged steps
  belong in packaging or the image build and must be reviewed.
- Never edit files under `/usr/share/gnome-shell` or other system paths
  during development. Use the user-level install scripts in `scripts/`.
- Use colors, spacing and motion from `design/tokens/tokens.json` instead of
  hardcoding them.
- Extensions: ES modules, `shell-version` matching `config/platform.json`,
  and a full teardown in `disable()`.
- Do risky integration work (sessions, GDM, boot) in a VM with a snapshot.
