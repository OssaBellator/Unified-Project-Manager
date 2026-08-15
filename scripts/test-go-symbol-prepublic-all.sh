#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

sh "$ROOT/scripts/test-go-symbol-reachability.sh"
sh "$ROOT/scripts/test-go-symbol-sbom-contract.sh"
sh "$ROOT/scripts/test-go-symbol-scan-declaration.sh"
sh "$ROOT/scripts/test-go-symbol-build-selection.sh"
sh "$ROOT/scripts/test-go-symbol-source-observation.sh"
sh "$ROOT/scripts/test-go-symbol-source-alignment.sh"
sh "$ROOT/scripts/test-go-symbol-frame-source-alignment.sh"
sh "$ROOT/scripts/test-go-symbol-side-effects.sh"
sh "$ROOT/scripts/test-go-symbol-real-alignment.sh"
