#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_uv_workspace.py"
python3 "$ROOT/tests/test_uv_workspace_health.py"
python3 "$ROOT/tests/test_uv_workspace_operations.py"
python3 "$ROOT/tests/test_uv_workspace_batch_entrypoint.py"
