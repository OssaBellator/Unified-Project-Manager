#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_yarn_graph.py \
  tests/test_yarn_execution_compat.py \
  tests/test_yarn_impact.py \
  tests/test_yarn_provider_entrypoint.py \
  tests/test_yarn_why_impact_entrypoint.py \
  tests/test_yarn_sbom_merge.py \
  tests/test_yarn_sbom_scope.py \
  tests/test_yarn_sbom_entrypoint.py \
  tests/test_yarn_security_impact.py \
  tests/test_yarn_native_audit.py \
  tests/test_yarn_fleet_audit.py
 do
  python3 "$ROOT/$test_file"
 done
