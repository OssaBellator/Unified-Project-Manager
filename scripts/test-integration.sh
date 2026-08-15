#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

for test_file in \
  tests/test_batch_operation_entrypoint.py \
  tests/test_operation_receipt_entrypoint.py \
  tests/test_exec_receipt_entrypoint.py \
  tests/test_repair_receipt_entrypoint.py \
  tests/test_init_receipt_entrypoint.py \
  tests/test_receipt_post_verification.py \
  tests/test_public_provider_integration.py \
  tests/test_spdx_uv_semantics.py \
  tests/test_status_evidence_integration.py \
  tests/test_audit_status_integration.py \
  tests/test_go_offline_provider.py
 do
  python3 "$ROOT/$test_file"
 done
