#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

sh "$ROOT/scripts/check.sh"
sh "$ROOT/scripts/test-integration.sh"
sh "$ROOT/scripts/test-native-security.sh"
