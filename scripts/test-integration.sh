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
  tests/test_workspace_sync_receipts.py \
  tests/test_receipt_post_verification.py \
  tests/test_receipt_entrypoint.py \
  tests/test_public_provider_integration.py \
  tests/test_npm_graph.py \
  tests/test_npm_sbom.py \
  tests/test_npm_sbom_entrypoint.py \
  tests/test_pnpm_graph.py \
  tests/test_pnpm_provider_entrypoint.py \
  tests/test_pnpm_sbom.py \
  tests/test_pnpm_sbom_entrypoint.py \
  tests/test_yarn_graph.py \
  tests/test_yarn_impact.py \
  tests/test_yarn_provider_entrypoint.py \
  tests/test_yarn_why_impact_entrypoint.py \
  tests/test_yarn_sbom_merge.py \
  tests/test_yarn_sbom_entrypoint.py \
  tests/test_yarn_security_impact.py \
  tests/test_yarn_native_audit.py \
  tests/test_cargo_graph.py \
  tests/test_cargo_workspace.py \
  tests/test_uv_graph.py \
  tests/test_uv_workspace.py \
  tests/test_uv_workspace_health.py \
  tests/test_uv_workspace_operations.py \
  tests/test_uv_workspace_batch_entrypoint.py \
  tests/test_uv_workspace_provider_routing.py \
  tests/test_uv_workspace_sbom_routing.py \
  tests/test_provider_selection.py \
  tests/test_provider_ownership.py \
  tests/test_provider_registry.py \
  tests/test_security_impact.py \
  tests/test_workspace_health.py \
  tests/test_fleet_provider_entrypoint.py \
  tests/test_fleet_status_entrypoint.py \
  tests/test_fleet_security.py \
  tests/test_fleet_audit_evidence_integration.py \
  tests/test_spdx_uv_semantics.py \
  tests/test_status_evidence_integration.py \
  tests/test_audit_status_integration.py \
  tests/test_go_offline_provider.py
 do
  python3 "$ROOT/$test_file"
 done
