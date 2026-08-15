#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/test_native_cyclonedx.py"
python3 "$ROOT/tests/test_security_native_providers.py"
python3 "$ROOT/tests/test_security_impact.py"
