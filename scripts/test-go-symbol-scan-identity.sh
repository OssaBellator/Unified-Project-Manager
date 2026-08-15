#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_go-symbol-scan-identity.py" 2>/dev/null && exit 0
python3 "$ROOT/tests/test_go_symbol_scan_identity.py"
