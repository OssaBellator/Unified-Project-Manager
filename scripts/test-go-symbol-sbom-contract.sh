#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_go_symbol_reachability.py"
python3 "$ROOT/tests/test_go_symbol_correlation.py"
python3 "$ROOT/tests/test_go_symbol_execution.py"
python3 "$ROOT/tests/test_go_symbol_reporting.py"
python3 "$ROOT/tests/test_go_symbol_scan_identity.py"
