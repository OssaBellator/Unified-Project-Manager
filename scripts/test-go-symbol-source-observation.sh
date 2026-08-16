#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src:$ROOT/tests${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_go_symbol_source_observation.py"
python3 "$ROOT/tests/test_go_symbol_source_observation_fail_closed.py"
python3 "$ROOT/tests/test_go_symbol_source_observation_protocol_strict.py"
python3 "$ROOT/tests/test_go_symbol_source_observation_identity_strict.py"
python3 "$ROOT/tests/test_go_symbol_effective_environment.py"
python3 "$ROOT/tests/test_go_symbol_source_observation_real.py"
