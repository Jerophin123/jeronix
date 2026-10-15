#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs the JERONIX test suites. Usage: scripts/run-tests.sh [unit|integration|all]
# Needs no root and does not modify the running desktop session.
set -uo pipefail

cd "$(dirname "$0")/.."
suite="${1:-all}"
status=0

run() {
    echo "==> $*"
    "$@" || status=1
}

if [[ "$suite" == unit || "$suite" == all ]]; then
    run python3 scripts/jeronix_design.py check
    run python3 -m unittest discover -s tests/unit -p "test_*.py" -v
    for t in tests/unit/js/test_*.js; do
        run gjs -m "$t"
    done
fi

if [[ "$suite" == integration || "$suite" == all ]]; then
    for t in tests/integration/extension_lifecycle.py tests/integration/theme_lifecycle.py; do
        echo "==> python3 $t"
        python3 "$t"
        rc=$?
        if [[ $rc -eq 77 ]]; then
            echo "SKIPPED: integration prerequisites missing for $t"
        elif [[ $rc -ne 0 ]]; then
            status=1
        fi
    done
fi

if [[ $status -eq 0 ]]; then echo "ALL PASSED ($suite)"; else echo "FAILURES ($suite)"; fi
exit $status
