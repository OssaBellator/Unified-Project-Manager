#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_python_lock_graph.py"
python3 "$ROOT/tests/test_python_lock_reachability.py"
python3 "$ROOT/tests/test_python_lock_sbom.py"
