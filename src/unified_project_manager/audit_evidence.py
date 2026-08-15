from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

AUDIT_EVIDENCE_VERSION = 1
DEFAULT_AUDIT_PATH = Path(".upm/audits/osv.json")


class AuditEvidenceError(ValueError):
    """Raised when persisted advisory evidence is invalid or unsupported."""


def canonical_bom_bytes(bom: dict[str, Any]) -> bytes:
    return (json.dumps(bom, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def bom_sha256(bom: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bom_bytes(bom)).hexdigest()


@dataclass(frozen=True)
class AuditEvidence:
    version: int
    scanner: str
    generated_at: str
    bom_sha256: str
    package_count: int
    inventory_mode: str
    scanner_returncode: int
    vulnerable: bool
    affected_packages: int
    vulnerabilities: int
    report: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "scanner": self.scanner,
            "generated_at": self.generated_at,
            "bom_sha256": self.bom_sha256,
            "package_count": self.package_count,
            "inventory_mode": self.inventory_mode,
            "scanner_returncode": self.scanner_returncode,
            "vulnerable": self.vulnerable,
            "summary": {
                "affected_packages": self.affected_packages,
                "vulnerabilities": self.vulnerabilities,
            },
            "report": self.report,
        }


def build_audit_evidence(
    bom: dict[str, Any],
    scan_result: object,
    *,
    scanner: str = "osv-scanner",
    inventory_mode: str = "static-resolved",
    now: Callable[[], datetime] | None = None,
) -> AuditEvidence:
    report = getattr(scan_result, "report", None)
    summary = getattr(scan_result, "summary", {})
    returncode = getattr(scan_result, "returncode", None)
    vulnerable = getattr(scan_result, "vulnerable", None)
    if not isinstance(returncode, int) or not isinstance(vulnerable, bool):
        raise AuditEvidenceError("Scan result does not expose a stable returncode/vulnerable result.")
    if report is not None and not isinstance(report, dict):
        raise AuditEvidenceError("Scan report must be a JSON object or null.")
    if not isinstance(summary, dict):
        raise AuditEvidenceError("Scan result summary is invalid.")
    affected = summary.get("affected_packages", 0)
    vulnerabilities = summary.get("vulnerabilities", 0)
    if not isinstance(affected, int) or not isinstance(vulnerabilities, int):
        raise AuditEvidenceError("Scan summary counts must be integers.")
    components = bom.get("components")
    package_count = len(components) if isinstance(components, list) else 0
    current = (now or (lambda: datetime.now(timezone.utc)))()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    generated_at = current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return AuditEvidence(
        version=AUDIT_EVIDENCE_VERSION,
        scanner=scanner,
        generated_at=generated_at,
        bom_sha256=bom_sha256(bom),
        package_count=package_count,
        inventory_mode=inventory_mode,
        scanner_returncode=returncode,
        vulnerable=vulnerable,
        affected_packages=affected,
        vulnerabilities=vulnerabilities,
        report=report,
    )


def write_audit_evidence(
    root: str | Path,
    evidence: AuditEvidence,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = (root_path / DEFAULT_AUDIT_PATH) if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def load_audit_evidence(root: str | Path, path: str | Path | None = None) -> AuditEvidence | None:
    root_path = Path(root).expanduser().resolve()
    target = (root_path / DEFAULT_AUDIT_PATH) if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditEvidenceError(f"Could not read audit evidence {target}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != AUDIT_EVIDENCE_VERSION:
        raise AuditEvidenceError(f"Unsupported or invalid audit evidence: {target}")
    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise AuditEvidenceError(f"Audit evidence summary is invalid: {target}")
    required_strings = ("scanner", "generated_at", "bom_sha256", "inventory_mode")
    if not all(isinstance(data.get(name), str) for name in required_strings):
        raise AuditEvidenceError(f"Audit evidence identity fields are invalid: {target}")
    package_count = data.get("package_count")
    returncode = data.get("scanner_returncode")
    vulnerable = data.get("vulnerable")
    affected = summary.get("affected_packages")
    vulnerabilities = summary.get("vulnerabilities")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (package_count, returncode, affected, vulnerabilities)):
        raise AuditEvidenceError(f"Audit evidence numeric fields are invalid: {target}")
    if not isinstance(vulnerable, bool):
        raise AuditEvidenceError(f"Audit evidence vulnerable flag is invalid: {target}")
    report = data.get("report")
    if report is not None and not isinstance(report, dict):
        raise AuditEvidenceError(f"Audit evidence report is invalid: {target}")
    return AuditEvidence(
        version=AUDIT_EVIDENCE_VERSION,
        scanner=data["scanner"],
        generated_at=data["generated_at"],
        bom_sha256=data["bom_sha256"],
        package_count=package_count,
        inventory_mode=data["inventory_mode"],
        scanner_returncode=returncode,
        vulnerable=vulnerable,
        affected_packages=affected,
        vulnerabilities=vulnerabilities,
        report=report,
    )


def audit_evidence_matches(evidence: AuditEvidence, bom: dict[str, Any]) -> bool:
    return evidence.bom_sha256 == bom_sha256(bom)
