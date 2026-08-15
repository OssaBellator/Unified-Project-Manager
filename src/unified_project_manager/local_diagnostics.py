from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .advisory_v2_status import evaluate_advisory_v2_status
from .duplicate_classification import classify_duplicates
from .environment_inspection import inspect_environment
from .evidence_manifest import DEFAULT_EVIDENCE_MANIFEST_PATH
from .evidence_semantics import validate_project_evidence
from .models import ProjectGraph
from .receipt_history import latest_receipt_drift
from .state import integrity_findings
from .tool_resolution import collect_tool_resolution
from .tool_resolution_state import (
    DEFAULT_TOOL_RESOLUTION_STATE_PATH,
    ToolResolutionStateError,
    compare_tool_resolution_state,
    load_tool_resolution_state,
)


@dataclass(frozen=True)
class LocalDiagnostics:
    root: str
    integrity: tuple[dict[str, Any], ...]
    environment: dict[str, Any]
    tools: dict[str, Any]
    tool_baseline: dict[str, Any]
    receipts: dict[str, Any]
    advisory_v2: dict[str, Any]
    duplicates: dict[str, Any]
    evidence: dict[str, Any]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "integrity": list(self.integrity),
            "environment": self.environment,
            "tools": self.tools,
            "tool_baseline": self.tool_baseline,
            "receipts": self.receipts,
            "advisory_v2": self.advisory_v2,
            "duplicates": self.duplicates,
            "evidence": self.evidence,
            "summary": self.summary,
            "execution": {
                "manager_toolchain_binaries_executed": False,
                "native_graph_providers_executed": False,
                "scanner_execution": False,
                "network_executed": False,
                "mutation_executed": False,
                "physical_artifact_hash_scan_executed": False,
            },
        }


def _tool_baseline_status(graph: ProjectGraph, current_tools) -> dict[str, Any]:
    target = graph.root / DEFAULT_TOOL_RESOLUTION_STATE_PATH
    if not target.is_file():
        return {
            "state": "absent",
            "current": False,
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "reason": "No execution-safe machine-local tool baseline exists.",
            "version_probes_required": False,
        }
    try:
        baseline = load_tool_resolution_state(graph.root)
    except ToolResolutionStateError as exc:
        return {
            "state": "invalid",
            "current": False,
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "reason": str(exc),
            "version_probes_required": False,
        }
    if baseline is None:
        return {
            "state": "absent",
            "current": False,
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "reason": "No execution-safe machine-local tool baseline exists.",
            "version_probes_required": False,
        }
    if baseline.version_probes_executed:
        status = compare_tool_resolution_state(baseline, None)
        return {
            **status.to_dict(),
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "version_probes_required": True,
        }
    status = compare_tool_resolution_state(baseline, current_tools)
    return {
        **status.to_dict(),
        "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
        "version_probes_required": False,
    }


def collect_local_diagnostics(
    graph: ProjectGraph,
    *,
    environ: Mapping[str, str] | None = None,
) -> LocalDiagnostics:
    integrity = tuple(item.to_dict() for item in integrity_findings(graph))
    environment = inspect_environment(graph, environ=environ).to_dict()
    tools_report = collect_tool_resolution(graph, probe_versions=False)
    tools = tools_report.to_dict()
    tool_baseline = _tool_baseline_status(graph, tools_report)
    receipts = latest_receipt_drift(graph).to_dict()
    advisory_v2 = evaluate_advisory_v2_status(graph).to_dict()
    duplicates = classify_duplicates(graph).to_dict()

    evidence_path = graph.root / DEFAULT_EVIDENCE_MANIFEST_PATH
    if evidence_path.is_file():
        evidence_validation = validate_project_evidence(graph.root)
        evidence = evidence_validation.to_dict()
    else:
        evidence = {
            "valid": None,
            "state": "absent",
            "reason": "No project evidence manifest exists.",
            "authenticated": False,
        }

    integrity_errors = sum(item.get("severity") == "error" for item in integrity)
    integrity_warnings = sum(item.get("severity") == "warning" for item in integrity)
    environment_warnings = sum(
        item.get("severity") == "warning" for item in environment.get("findings", [])
    )
    unavailable_tools = sum(
        not item.get("available", False) for item in tools.get("observations", [])
    )
    requirement_divergences = len(tools.get("divergences", []))
    duplicate_observations = len(duplicates.get("observations", []))

    blockers: list[str] = []
    if integrity_errors:
        blockers.append("integrity")
    if receipts.get("state") not in {"absent", "current"}:
        blockers.append("receipts")
    if tool_baseline.get("state") in {"drifted", "invalid"}:
        blockers.append("tool-baseline")
    if advisory_v2.get("state") in {"invalid", "current-vulnerable"}:
        blockers.append("advisory-v2")
    if evidence.get("valid") is False:
        blockers.append("evidence-manifest")

    cautions: list[str] = []
    if integrity_warnings:
        cautions.append("integrity-warnings")
    if environment_warnings:
        cautions.append("environment-leakage")
    if unavailable_tools:
        cautions.append("unavailable-tools")
    if requirement_divergences:
        cautions.append("tool-requirement-divergence")
    if tool_baseline.get("state") == "probe-required":
        cautions.append("tool-version-probe-required")
    if advisory_v2.get("state") in {
        "stale-inventory",
        "expired",
        "native-inventory-unverified",
        "unknown-inventory-mode",
    }:
        cautions.append("advisory-v2-freshness")
    if duplicate_observations:
        cautions.append("duplicate-observations")

    summary = {
        "blockers": blockers,
        "cautions": cautions,
        "integrity_errors": integrity_errors,
        "integrity_warnings": integrity_warnings,
        "environment_warnings": environment_warnings,
        "unavailable_tools": unavailable_tools,
        "tool_requirement_divergences": requirement_divergences,
        "duplicate_observations": duplicate_observations,
        "strict_failed": bool(blockers or cautions),
    }
    return LocalDiagnostics(
        root=str(graph.root),
        integrity=integrity,
        environment=environment,
        tools=tools,
        tool_baseline=tool_baseline,
        receipts=receipts,
        advisory_v2=advisory_v2,
        duplicates=duplicates,
        evidence=evidence,
        summary=summary,
    )
