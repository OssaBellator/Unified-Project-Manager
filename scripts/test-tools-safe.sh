#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_tool_resolution.py \
  tests/test_tool_resolution_entrypoint.py \
  tests/test_tool_resolution_state.py \
  tests/test_tool_resolution_state_entrypoint.py
 do
  python3 "$ROOT/$test_file"
 done
