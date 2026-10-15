#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds out/iso/jeronix-26.04-x86_64.iso from the official Ubuntu 26.04
# Desktop ISO. No root needed. See build/iso/README.md.
#
# Usage: scripts/build-iso.sh [--source-iso FILE] [--out DIR] [--work DIR]
#                             [--keep-work] [--skip-tests] [--offline]
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 build/iso/jeronix_iso.py "$@"
