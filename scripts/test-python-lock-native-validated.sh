#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_python_lock_provider.py \
  tests/test_python_lock_validation.py \
  tests/test_python_lock_graph.py \
  tests/test_python_lock_reachability.py \
  tests/test_python_lock_path_multiplicity.py \
  tests/test_python_lock_sbom.py \
  tests/test_python_lock_sbom_uncertainty.py
 do
  python3 "$ROOT/$test_file"
 done
