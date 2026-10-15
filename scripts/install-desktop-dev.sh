#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installs the JERONIX desktop identity (shell theme extension, wallpapers,
# icons) for the current user, for manual testing. No root; only files under
# $XDG_DATA_HOME (~/.local/share) are written, and every installed path is
# recorded so --remove deletes exactly what was installed.
#
# Nothing is switched on: the theme extension is not enabled and no settings
# or wallpaper are changed. See docs/development/desktop-identity.md.
#
# Usage: scripts/install-desktop-dev.sh            build and install
#        scripts/install-desktop-dev.sh --remove   uninstall
#        scripts/install-desktop-dev.sh --remove --force   uninstall even if a
#                                                  JERONIX wallpaper is in use
set -euo pipefail

cd "$(dirname "$0")/.."
data="${XDG_DATA_HOME:-$HOME/.local/share}"
manifest="$data/jeronix/dev-install.manifest"
# Extensions built from desktop/extensions (all JERONIX UUIDs end in @jeronix).
uuids=(jeronix-shell-theme@jeronix jeronix-panel@jeronix jeronix-dock@jeronix jeronix-quick-settings@jeronix)
wallpaper_dir="$data/backgrounds/jeronix"

remove=0
force=0
for arg in "$@"; do
    case "$arg" in
        --remove) remove=1 ;;
        --force) force=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

wallpaper_in_use() {
    command -v gsettings >/dev/null || return 1
    local key value
    for key in "org.gnome.desktop.background picture-uri" \
               "org.gnome.desktop.background picture-uri-dark" \
               "org.gnome.desktop.screensaver picture-uri"; do
        # shellcheck disable=SC2086
        value="$(gsettings get $key 2>/dev/null || true)"
        [[ "$value" == *"$wallpaper_dir/"* ]] && return 0
    done
    return 1
}

if [[ $remove -eq 1 ]]; then
    if [[ ! -f "$manifest" ]]; then
        echo "nothing to remove (no $manifest)"
        exit 0
    fi
    if [[ $force -eq 0 ]] && wallpaper_in_use; then
        echo "A JERONIX wallpaper is still set. Restore your previous settings first:" >&2
        echo "  scripts/jeronix_layout.py restore" >&2
        echo "or re-run with --force to remove anyway." >&2
        exit 1
    fi
    # Unload the stylesheet from the running shell before deleting it.
    for uuid in "${uuids[@]}"; do
        gnome-extensions disable "$uuid" 2>/dev/null || true
    done
    while IFS= read -r path; do
        # Only ever delete inside the data directory.
        [[ "$path" == "$data/"* ]] || { echo "skipping unexpected path $path" >&2; continue; }
        rm -rf -- "$path"
    done < "$manifest"
    rm -f -- "$manifest"
    rmdir --ignore-fail-on-non-empty "$data/jeronix" 2>/dev/null || true
    echo "removed JERONIX desktop identity from $data"
    exit 0
fi

build="$(mktemp -d "${TMPDIR:-/tmp}/jeronix-build-XXXXXX")"
trap 'rm -rf -- "$build"' EXIT
python3 scripts/jeronix_design.py build --out "$build" >/dev/null

installed=()
put() {  # put <source> <destination>
    mkdir -p "$(dirname "$2")"
    rm -rf -- "$2"
    cp -r -- "$1" "$2"
    installed+=("$2")
}

for uuid in "${uuids[@]}"; do
    put "$build/extensions/$uuid" "$data/gnome-shell/extensions/$uuid"
done
put "$build/wallpapers/jeronix-dark-3840x2160.png" "$wallpaper_dir/jeronix-dark.png"
put "$build/wallpapers/jeronix-light-3840x2160.png" "$wallpaper_dir/jeronix-light.png"

properties="$data/gnome-background-properties/jeronix.xml"
mkdir -p "$(dirname "$properties")"
cat > "$properties" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">
<wallpapers>
  <wallpaper deleted="false">
    <name>JERONIX</name>
    <filename>$wallpaper_dir/jeronix-light.png</filename>
    <filename-dark>$wallpaper_dir/jeronix-dark.png</filename-dark>
    <options>zoom</options>
    <shade_type>solid</shade_type>
    <pcolor>#1E1D1B</pcolor>
    <scolor>#1E1D1B</scolor>
  </wallpaper>
</wallpapers>
EOF
installed+=("$properties")

while IFS= read -r icon; do
    put "$build/icons/hicolor/$icon" "$data/icons/hicolor/$icon"
done < <(cd "$build/icons/hicolor" && find . -type f | sed 's|^\./||' | sort)

mkdir -p "$(dirname "$manifest")"
printf '%s\n' "${installed[@]}" > "$manifest"

echo "installed JERONIX desktop identity into $data (${#installed[@]} items, listed in $manifest)"
echo
echo "Nothing has been switched on. Next steps:"
echo "  1. Log out and back in once (Wayland) so GNOME Shell discovers the extensions."
echo "  2. gnome-extensions enable jeronix-shell-theme@jeronix   (and jeronix-panel@jeronix, jeronix-dock@jeronix)"
echo "     Each one applies live; gnome-extensions disable undoes it."
echo "  3. scripts/jeronix_layout.py plan desktop/layouts/pure.json"
echo "     scripts/jeronix_layout.py apply desktop/layouts/pure.json   # live; 'restore' undoes it"
