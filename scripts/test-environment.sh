#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_environment_inspection.py"
python3 "$ROOT/tests/test_environment_entrypoint.py"
