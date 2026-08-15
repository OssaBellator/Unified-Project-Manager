#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_duplicate_classification.py \
  tests/test_duplicate_entrypoint.py \
  tests/test_dedupe_operation.py \
  tests/test_dedupe_entrypoint.py
 do
  python3 "$ROOT/$test_file"
 done
