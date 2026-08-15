#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_receipt_post_verification.py \
  tests/test_receipt_v2_integrity.py \
  tests/test_receipt_redaction.py \
  tests/test_receipt_entrypoint.py \
  tests/test_advisory_evidence_v2.py \
  tests/test_evidence_manifest.py \
  tests/test_evidence_manifest_entrypoint.py \
  tests/test_status_evidence_integration.py \
  tests/test_audit_status_integration.py \
  tests/test_fleet_audit_evidence_integration.py
 do
  python3 "$ROOT/$test_file"
 done
