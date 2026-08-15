#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_receipts.py \
  tests/test_receipt_post_verification.py \
  tests/test_receipt_v2_integrity.py \
  tests/test_receipt_redaction.py \
  tests/test_receipt_chain.py \
  tests/test_receipt_entrypoint.py \
  tests/test_advisory_evidence_v2.py \
  tests/test_advisory_v2_entrypoint.py \
  tests/test_advisory_v2_status.py \
  tests/test_advisory_v2_status_entrypoint.py \
  tests/test_evidence_manifest.py \
  tests/test_evidence_manifest_entrypoint.py \
  tests/test_evidence_semantics.py \
  tests/test_evidence_semantics_entrypoint.py
 do
  python3 "$ROOT/$test_file"
 done
