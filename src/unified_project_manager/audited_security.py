from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .audit_evidence import AuditEvidence, build_audit_evidence, write_audit_evidence
from .models import ProjectGraph
from .security import SecurityScanPlan, SecurityScanResult, build_security_bom, execute_security_scan


@dataclass(frozen=True)
class PersistedSecurityScan:
    result: SecurityScanResult
    evidence: AuditEvidence | None
    evidence_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.to_dict(),
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
        }


def execute_and_persist_security_scan(
    graph: ProjectGraph,
    plan: SecurityScanPlan,
    *,
    evidence_path: str | Path | None = None,
    execute_scan: Callable[..., SecurityScanResult] = execute_security_scan,
) -> PersistedSecurityScan:
    """Run an explicit scan and persist evidence only for valid scanner outcomes.

    Scanner failures are never written as advisory evidence. Exit code 1 is a
    valid vulnerable result and is persisted. The fingerprint is calculated
    from the same inventory mode the scan plan requested.
    """
    result = execute_scan(graph, plan)
    if not result.scanner_succeeded:
        return PersistedSecurityScan(result, None, None)
    bom = build_security_bom(graph, native_go=plan.native_go)
    mode = "native-go-enriched" if plan.native_go else "static-resolved"
    evidence = build_audit_evidence(bom, result, inventory_mode=mode)
    written = write_audit_evidence(graph.root, evidence, evidence_path)
    return PersistedSecurityScan(result, evidence, written)
