from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .advisory_evidence_v2 import (
    AdvisoryEvidenceV2,
    DEFAULT_ADVISORY_PATH,
    load_advisory_evidence_v2,
)
from .models import ProjectGraph
from .sbom import cyclonedx_bom


@dataclass(frozen=True)
class AdvisoryV2Status:
    state: str
    path: str
    present: bool
    valid: bool | None
    current: bool | None
    vulnerable: bool | None
    vulnerabilities: int | None
    affected_packages: int | None
    vulnerability_ids: tuple[str, ...]
    inventory_mode: str | None
    scanned_at: str | None
    evidence_id: str | None
    age_seconds: int | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['vulnerability_ids'] = list(self.vulnerability_ids)
        return data


def _parse_time(value: str) -> datetime | None:
    try:
        normalized = value[:-1] + '+00:00' if value.endswith('Z') else value
        result = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _status_from_evidence(
    evidence: AdvisoryEvidenceV2,
    *,
    current: bool | None,
    age_seconds: int | None,
    state: str,
    reason: str | None = None,
) -> AdvisoryV2Status:
    summary = evidence.summary
    return AdvisoryV2Status(
        state=state,
        path=DEFAULT_ADVISORY_PATH.as_posix(),
        present=True,
        valid=True,
        current=current,
        vulnerable=evidence.vulnerable,
        vulnerabilities=summary.vulnerabilities,
        affected_packages=summary.affected_packages,
        vulnerability_ids=summary.vulnerability_ids,
        inventory_mode=evidence.inventory_mode,
        scanned_at=evidence.scanned_at,
        evidence_id=evidence.evidence_id,
        age_seconds=age_seconds,
        reason=reason,
    )


def evaluate_advisory_v2_status(
    graph: ProjectGraph,
    *,
    max_age_seconds: int | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> AdvisoryV2Status:
    target = graph.root / DEFAULT_ADVISORY_PATH
    if not target.is_file():
        return AdvisoryV2Status(
            'absent', DEFAULT_ADVISORY_PATH.as_posix(), False, None, None, None,
            None, None, (), None, None, None, None,
            'No advisory evidence v2 file exists.',
        )

    initial = load_advisory_evidence_v2(graph.root)
    if not initial.valid or initial.evidence is None:
        return AdvisoryV2Status(
            'invalid', DEFAULT_ADVISORY_PATH.as_posix(), True, False, None, None,
            None, None, (), None, None, None, None,
            initial.reason or 'Advisory evidence v2 is invalid.',
        )
    evidence = initial.evidence

    scanned = _parse_time(evidence.scanned_at)
    age_seconds = None
    if scanned is not None:
        current_time = now()
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        age_seconds = max(0, int((current_time.astimezone(timezone.utc) - scanned).total_seconds()))
    if max_age_seconds is not None:
        if max_age_seconds < 0:
            raise ValueError('max_age_seconds must be non-negative.')
        if age_seconds is None:
            return _status_from_evidence(
                evidence,
                current=None,
                age_seconds=None,
                state='invalid-time',
                reason='Advisory evidence scan timestamp cannot be interpreted.',
            )
        if age_seconds > max_age_seconds:
            return _status_from_evidence(
                evidence,
                current=False,
                age_seconds=age_seconds,
                state='expired',
                reason=f'Advisory evidence is older than the allowed {max_age_seconds} seconds.',
            )

    if evidence.inventory_mode == 'static-resolved':
        current_bom = cyclonedx_bom(graph)
        validation = load_advisory_evidence_v2(graph.root, bom=current_bom)
        if not validation.valid:
            reason = validation.reason or 'Current static dependency inventory differs from the scanned BOM.'
            if 'BOM' in reason or 'bom' in reason:
                return _status_from_evidence(
                    evidence,
                    current=False,
                    age_seconds=age_seconds,
                    state='stale-inventory',
                    reason=reason,
                )
            return AdvisoryV2Status(
                'invalid', DEFAULT_ADVISORY_PATH.as_posix(), True, False, None, None,
                None, None, (), evidence.inventory_mode, evidence.scanned_at,
                evidence.evidence_id, age_seconds, reason,
            )
        return _status_from_evidence(
            evidence,
            current=True,
            age_seconds=age_seconds,
            state='current-vulnerable' if evidence.vulnerable else 'current-clean',
        )

    if evidence.inventory_mode == 'native-go':
        return _status_from_evidence(
            evidence,
            current=None,
            age_seconds=age_seconds,
            state='native-inventory-unverified',
            reason=(
                'The scan used native Go inventory. Ordinary local status does not rerun native providers, '
                'so current inventory equivalence is intentionally unverified.'
            ),
        )

    return _status_from_evidence(
        evidence,
        current=None,
        age_seconds=age_seconds,
        state='unknown-inventory-mode',
        reason=f'No local freshness strategy is defined for inventory mode {evidence.inventory_mode!r}.',
    )
