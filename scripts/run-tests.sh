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
    run python3 -m unittest discover -s tests/unit -p "test_*.py" -v
    for t in tests/unit/js/test_*.js; do
        run gjs -m "$t"
    done
fi

if [[ "$suite" == integration || "$suite" == all ]]; then
    echo "==> python3 tests/integration/extension_lifecycle.py"
    python3 tests/integration/extension_lifecycle.py
    rc=$?
    if [[ $rc -eq 77 ]]; then
        echo "SKIPPED: integration prerequisites missing"
    elif [[ $rc -ne 0 ]]; then
        status=1
    fi
fi

if [[ $status -eq 0 ]]; then echo "ALL PASSED ($suite)"; else echo "FAILURES ($suite)"; fi
exit $status
