#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copies a JERONIX extension into the current user's extension directory for
# manual testing. No root needed; nothing outside ~/.local/share is touched.
#
# Usage: scripts/install-extension-dev.sh <extension-dir-name>   (e.g. jeronix-quick-settings)
#        scripts/install-extension-dev.sh --remove <extension-dir-name>
set -euo pipefail

cd "$(dirname "$0")/.."
remove=0
if [[ "${1:-}" == --remove ]]; then remove=1; shift; fi
name="${1:?extension directory name required}"
src="desktop/extensions/$name"
[[ -f "$src/metadata.json" ]] || { echo "no extension at $src" >&2; exit 1; }

uuid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["uuid"])' "$src/metadata.json")"
dest="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$uuid"

if [[ $remove -eq 1 ]]; then
    gnome-extensions disable "$uuid" 2>/dev/null || true
    rm -rf -- "$dest"
    echo "removed $dest"
    exit 0
fi

mkdir -p "$dest"
cp -r "$src"/. "$dest"/
echo "installed $uuid -> $dest"
echo "On Wayland, log out and back in once so GNOME Shell discovers it, then run:"
echo "  gnome-extensions enable $uuid"
