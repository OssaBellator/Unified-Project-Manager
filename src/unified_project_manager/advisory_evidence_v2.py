from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ADVISORY_EVIDENCE_VERSION = 2
DEFAULT_ADVISORY_PATH = Path('.upm/audits/osv-v2.json')


class AdvisoryEvidenceError(ValueError):
    """Raised when persisted advisory evidence is internally inconsistent."""


@dataclass(frozen=True)
class AdvisorySummary:
    affected_packages: int
    vulnerabilities: int
    vulnerability_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['vulnerability_ids'] = list(self.vulnerability_ids)
        return data


@dataclass(frozen=True)
class AdvisoryEvidenceV2:
    version: int
    evidence_id: str
    scanner: str
    scanner_returncode: int
    scanned_at: str
    inventory_mode: str
    bom_sha256: str
    report_sha256: str
    summary: AdvisorySummary
    report: Mapping[str, Any]

    @property
    def vulnerable(self) -> bool:
        return self.summary.vulnerabilities > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'evidence_id': self.evidence_id,
            'scanner': self.scanner,
            'scanner_returncode': self.scanner_returncode,
            'scanned_at': self.scanned_at,
            'inventory_mode': self.inventory_mode,
            'bom_sha256': self.bom_sha256,
            'report_sha256': self.report_sha256,
            'summary': self.summary.to_dict(),
            'report': dict(self.report),
        }


@dataclass(frozen=True)
class AdvisoryEvidenceValidation:
    valid: bool
    evidence: AdvisoryEvidenceV2 | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'valid': self.valid,
            'reason': self.reason,
            'evidence': self.evidence.to_dict() if self.evidence else None,
        }


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def summarize_osv_report(report: Mapping[str, Any]) -> AdvisorySummary:
    vulnerability_ids: set[str] = set()
    affected_packages = 0
    results = report.get('results')
    if results is None:
        return AdvisorySummary(0, 0, ())
    if not isinstance(results, list):
        raise AdvisoryEvidenceError('OSV report results must be an array when present.')

    for result in results:
        if not isinstance(result, dict):
            raise AdvisoryEvidenceError('OSV report result entry is not an object.')
        packages = result.get('packages')
        if packages is None:
            continue
        if not isinstance(packages, list):
            raise AdvisoryEvidenceError('OSV report packages must be an array when present.')
        for package in packages:
            if not isinstance(package, dict):
                raise AdvisoryEvidenceError('OSV report package entry is not an object.')
            vulnerabilities = package.get('vulnerabilities')
            if vulnerabilities is None:
                continue
            if not isinstance(vulnerabilities, list):
                raise AdvisoryEvidenceError('OSV report vulnerabilities must be an array when present.')
            if vulnerabilities:
                affected_packages += 1
            for vulnerability in vulnerabilities:
                if not isinstance(vulnerability, dict):
                    raise AdvisoryEvidenceError('OSV report vulnerability entry is not an object.')
                vulnerability_id = vulnerability.get('id')
                if isinstance(vulnerability_id, str) and vulnerability_id:
                    vulnerability_ids.add(vulnerability_id)

    ordered = tuple(sorted(vulnerability_ids))
    return AdvisorySummary(affected_packages, len(ordered), ordered)


def _identity_payload(
    *,
    scanner: str,
    scanner_returncode: int,
    scanned_at: str,
    inventory_mode: str,
    bom_sha256: str,
    report_sha256: str,
    summary: AdvisorySummary,
) -> dict[str, Any]:
    return {
        'version': ADVISORY_EVIDENCE_VERSION,
        'scanner': scanner,
        'scanner_returncode': scanner_returncode,
        'scanned_at': scanned_at,
        'inventory_mode': inventory_mode,
        'bom_sha256': bom_sha256,
        'report_sha256': report_sha256,
        'summary': summary.to_dict(),
    }


def _normalize_time(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def build_advisory_evidence_v2(
    bom: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    scanner_returncode: int,
    inventory_mode: str,
    scanner: str = 'osv-scanner',
    scanned_at: datetime | None = None,
) -> AdvisoryEvidenceV2:
    if scanner_returncode not in {0, 1}:
        raise AdvisoryEvidenceError(
            f'Cannot persist advisory evidence for scanner failure exit code {scanner_returncode}.'
        )
    if not isinstance(scanner, str) or not scanner.strip():
        raise AdvisoryEvidenceError('Scanner name must be a non-empty string.')
    if not isinstance(inventory_mode, str) or not inventory_mode.strip():
        raise AdvisoryEvidenceError('Inventory mode must be a non-empty string.')

    summary = summarize_osv_report(report)
    if scanner_returncode == 0 and summary.vulnerabilities:
        raise AdvisoryEvidenceError(
            'OSV scanner exit code 0 is inconsistent with a report containing vulnerability IDs.'
        )
    if scanner_returncode == 1 and summary.vulnerabilities == 0:
        raise AdvisoryEvidenceError(
            'OSV scanner exit code 1 is inconsistent with a report containing no vulnerability IDs.'
        )

    scanned_at_text = _normalize_time(scanned_at)
    bom_hash = canonical_sha256(bom)
    report_hash = canonical_sha256(report)
    payload = _identity_payload(
        scanner=scanner.strip(),
        scanner_returncode=scanner_returncode,
        scanned_at=scanned_at_text,
        inventory_mode=inventory_mode.strip(),
        bom_sha256=bom_hash,
        report_sha256=report_hash,
        summary=summary,
    )
    evidence_id = canonical_sha256(payload)
    return AdvisoryEvidenceV2(
        ADVISORY_EVIDENCE_VERSION,
        evidence_id,
        scanner.strip(),
        scanner_returncode,
        scanned_at_text,
        inventory_mode.strip(),
        bom_hash,
        report_hash,
        summary,
        dict(report),
    )


def _parse_summary(value: object) -> AdvisorySummary:
    if not isinstance(value, dict):
        raise AdvisoryEvidenceError('Advisory evidence summary must be an object.')
    affected = value.get('affected_packages')
    vulnerabilities = value.get('vulnerabilities')
    ids = value.get('vulnerability_ids')
    if not isinstance(affected, int) or isinstance(affected, bool) or affected < 0:
        raise AdvisoryEvidenceError('Advisory affected_packages must be a non-negative integer.')
    if not isinstance(vulnerabilities, int) or isinstance(vulnerabilities, bool) or vulnerabilities < 0:
        raise AdvisoryEvidenceError('Advisory vulnerabilities must be a non-negative integer.')
    if not isinstance(ids, list) or not all(isinstance(item, str) and item for item in ids):
        raise AdvisoryEvidenceError('Advisory vulnerability_ids must be an array of non-empty strings.')
    if ids != sorted(set(ids)):
        raise AdvisoryEvidenceError('Advisory vulnerability_ids must be unique and sorted.')
    if vulnerabilities != len(ids):
        raise AdvisoryEvidenceError('Advisory vulnerability count disagrees with vulnerability_ids.')
    return AdvisorySummary(affected, vulnerabilities, tuple(ids))


def validate_advisory_evidence_v2(
    value: Mapping[str, Any],
    *,
    bom: Mapping[str, Any] | None = None,
) -> AdvisoryEvidenceValidation:
    try:
        if value.get('version') != ADVISORY_EVIDENCE_VERSION:
            raise AdvisoryEvidenceError(
                f'Unsupported advisory evidence version {value.get("version")!r}.'
            )
        evidence_id = value.get('evidence_id')
        scanner = value.get('scanner')
        returncode = value.get('scanner_returncode')
        scanned_at = value.get('scanned_at')
        inventory_mode = value.get('inventory_mode')
        bom_hash = value.get('bom_sha256')
        report_hash = value.get('report_sha256')
        report = value.get('report')
        if not isinstance(evidence_id, str) or len(evidence_id) != 64:
            raise AdvisoryEvidenceError('Advisory evidence_id is invalid.')
        if not isinstance(scanner, str) or not scanner:
            raise AdvisoryEvidenceError('Advisory scanner is invalid.')
        if returncode not in {0, 1}:
            raise AdvisoryEvidenceError('Advisory scanner_returncode must be 0 or 1.')
        if not isinstance(scanned_at, str) or not scanned_at:
            raise AdvisoryEvidenceError('Advisory scanned_at is invalid.')
        if not isinstance(inventory_mode, str) or not inventory_mode:
            raise AdvisoryEvidenceError('Advisory inventory_mode is invalid.')
        if not isinstance(bom_hash, str) or len(bom_hash) != 64:
            raise AdvisoryEvidenceError('Advisory bom_sha256 is invalid.')
        if not isinstance(report_hash, str) or len(report_hash) != 64:
            raise AdvisoryEvidenceError('Advisory report_sha256 is invalid.')
        if not isinstance(report, dict):
            raise AdvisoryEvidenceError('Advisory report must be an object.')

        summary = _parse_summary(value.get('summary'))
        derived_summary = summarize_osv_report(report)
        if summary != derived_summary:
            raise AdvisoryEvidenceError(
                'Persisted advisory summary does not match the embedded OSV report.'
            )
        if returncode == 0 and summary.vulnerabilities:
            raise AdvisoryEvidenceError('Scanner exit code 0 disagrees with embedded vulnerability findings.')
        if returncode == 1 and summary.vulnerabilities == 0:
            raise AdvisoryEvidenceError('Scanner exit code 1 disagrees with embedded vulnerability findings.')
        if canonical_sha256(report) != report_hash:
            raise AdvisoryEvidenceError('Embedded OSV report does not match report_sha256.')
        if bom is not None and canonical_sha256(bom) != bom_hash:
            raise AdvisoryEvidenceError('Current/scanned BOM does not match bom_sha256.')

        payload = _identity_payload(
            scanner=scanner,
            scanner_returncode=returncode,
            scanned_at=scanned_at,
            inventory_mode=inventory_mode,
            bom_sha256=bom_hash,
            report_sha256=report_hash,
            summary=summary,
        )
        if canonical_sha256(payload) != evidence_id:
            raise AdvisoryEvidenceError('Advisory evidence_id does not match canonical evidence content.')

        evidence = AdvisoryEvidenceV2(
            ADVISORY_EVIDENCE_VERSION,
            evidence_id,
            scanner,
            returncode,
            scanned_at,
            inventory_mode,
            bom_hash,
            report_hash,
            summary,
            report,
        )
        return AdvisoryEvidenceValidation(True, evidence)
    except AdvisoryEvidenceError as exc:
        return AdvisoryEvidenceValidation(False, None, str(exc))


def write_advisory_evidence_v2(
    root: str | Path,
    evidence: AdvisoryEvidenceV2,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_ADVISORY_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise AdvisoryEvidenceError(f'Advisory evidence path escapes project root: {target}') from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def load_advisory_evidence_v2(
    root: str | Path,
    path: str | Path | None = None,
    *,
    bom: Mapping[str, Any] | None = None,
) -> AdvisoryEvidenceValidation:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_ADVISORY_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return AdvisoryEvidenceValidation(False, None, 'No advisory evidence v2 file exists.')
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return AdvisoryEvidenceValidation(False, None, f'Could not read advisory evidence: {exc}')
    if not isinstance(value, dict):
        return AdvisoryEvidenceValidation(False, None, 'Advisory evidence JSON root is not an object.')
    return validate_advisory_evidence_v2(value, bom=bom)
