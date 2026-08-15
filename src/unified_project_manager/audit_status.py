from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .audit_evidence import AuditEvidenceError, audit_evidence_matches, load_audit_evidence
from .models import ProjectGraph
from .sbom import cyclonedx_bom

AuditState = Literal[
    "absent",
    "current-clean",
    "current-vulnerable",
    "stale",
    "native-inventory-unverified",
    "invalid",
]


@dataclass(frozen=True)
class AuditEvidenceStatus:
    state: AuditState
    path: str
    scanner: str | None = None
    generated_at: str | None = None
    age_seconds: int | None = None
    inventory_mode: str | None = None
    vulnerabilities: int | None = None
    affected_packages: int | None = None
    reason: str | None = None

    @property
    def current(self) -> bool:
        return self.state in {"current-clean", "current-vulnerable"}

    @property
    def passed(self) -> bool:
        return self.state == "current-clean"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["current"] = self.current
        data["passed"] = self.passed
        return data


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_audit_status(
    graph: ProjectGraph,
    *,
    path: str | Path | None = None,
    max_age_seconds: int | None = None,
    now: Callable[[], datetime] | None = None,
) -> AuditEvidenceStatus:
    target = (graph.root / ".upm" / "audits" / "osv.json") if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (graph.root / target).resolve()
    try:
        evidence = load_audit_evidence(graph.root, target)
    except AuditEvidenceError as exc:
        return AuditEvidenceStatus("invalid", str(target), reason=str(exc))
    if evidence is None:
        return AuditEvidenceStatus("absent", str(target), reason="No persisted advisory evidence exists.")

    generated = _parse_time(evidence.generated_at)
    current_time = (now or (lambda: datetime.now(timezone.utc)))()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    age_seconds = None
    if generated is not None:
        age_seconds = max(0, int((current_time - generated).total_seconds()))

    common = {
        "path": str(target),
        "scanner": evidence.scanner,
        "generated_at": evidence.generated_at,
        "age_seconds": age_seconds,
        "inventory_mode": evidence.inventory_mode,
        "vulnerabilities": evidence.vulnerabilities,
        "affected_packages": evidence.affected_packages,
    }

    if evidence.inventory_mode != "static-resolved":
        return AuditEvidenceStatus(
            "native-inventory-unverified",
            reason="Evidence used native inventory that ordinary local status does not re-execute.",
            **common,
        )

    if not audit_evidence_matches(evidence, cyclonedx_bom(graph)):
        return AuditEvidenceStatus(
            "stale",
            reason="The current resolved-inventory SBOM fingerprint differs from the scanned evidence.",
            **common,
        )

    if max_age_seconds is not None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative.")
        if age_seconds is None or age_seconds > max_age_seconds:
            return AuditEvidenceStatus(
                "stale",
                reason=f"Advisory evidence exceeds the configured maximum age of {max_age_seconds} seconds.",
                **common,
            )

    if evidence.vulnerable:
        return AuditEvidenceStatus("current-vulnerable", **common)
    return AuditEvidenceStatus("current-clean", **common)
