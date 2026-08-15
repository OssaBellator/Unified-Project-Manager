#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_go_offline_provider.py"
python3 "$ROOT/tests/test_go_import_reachability.py"
python3 "$ROOT/tests/test_go_import_reachability_audit.py"
python3 "$ROOT/tests/test_go_mod_why_readonly.py"
