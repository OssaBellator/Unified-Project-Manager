#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 DESTINATION" >&2
  exit 2
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST=$1
export PYTHONPATH="$ROOT/tests:$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python3 "$ROOT/tests/support_go_symbol_runtime_fixture.py" "$DEST" --prepare --json
