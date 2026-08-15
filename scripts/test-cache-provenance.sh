#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_go_cache_provenance.py \
  tests/test_cargo_cache_provenance.py \
  tests/test_cache_provenance.py
 do
  python3 "$ROOT/$test_file"
 done
