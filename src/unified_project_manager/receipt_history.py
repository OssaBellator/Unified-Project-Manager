from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import ProjectGraph
from .receipts import (
    RECEIPT_DIRECTORY,
    SUPPORTED_RECEIPT_VERSIONS,
    StateObservation,
    capture_project_state,
    diff_project_state,
    receipt_identity_digest,
    receipt_identity_payload,
)


class ReceiptHistoryError(ValueError):
    """Raised when mutation receipt history cannot be interpreted safely."""


@dataclass(frozen=True)
class ReceiptValidation:
    path: str
    valid: bool
    receipt_id: str | None
    created_at: str | None
    operation: str | None
    succeeded: bool | None
    reason: str | None = None
    version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiptDriftStatus:
    state: str
    latest_receipt: ReceiptValidation | None
    changes: tuple[dict[str, Any], ...]
    invalid_receipts: tuple[ReceiptValidation, ...]
    reason: str | None = None

    @property
    def current(self) -> bool:
        return self.state == 'current'

    def to_dict(self) -> dict[str, Any]:
        return {
            'state': self.state,
            'current': self.current,
            'latest_receipt': self.latest_receipt.to_dict() if self.latest_receipt else None,
            'changes': list(self.changes),
            'invalid_receipts': [item.to_dict() for item in self.invalid_receipts],
            'reason': self.reason,
        }


def _expected_receipt_id(data: dict[str, Any], version: int) -> str:
    payload = receipt_identity_payload(
        version=version,
        operation=data.get('operation'),
        commands=data.get('commands'),
        before=data.get('before'),
        after=data.get('after'),
        created_at=data.get('created_at'),
        verification=data.get('verification'),
    )
    return receipt_identity_digest(payload)


def _observations(values: object) -> tuple[StateObservation, ...]:
    if not isinstance(values, list):
        raise ReceiptHistoryError('Receipt state observations must be arrays.')
    result: list[StateObservation] = []
    for value in values:
        if not isinstance(value, dict):
            raise ReceiptHistoryError('Receipt state observation is not an object.')
        path = value.get('path')
        kind = value.get('kind')
        digest = value.get('sha256')
        size = value.get('size')
        if not all(isinstance(item, str) for item in (path, kind, digest)):
            raise ReceiptHistoryError('Receipt state observation identity is invalid.')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ReceiptHistoryError('Receipt state observation size is invalid.')
        result.append(StateObservation(path, kind, digest, size))
    return tuple(result)


def _validation(
    target: Path,
    valid: bool,
    receipt_id: str | None,
    created_at: str | None,
    operation: str | None,
    succeeded: bool | None,
    reason: str | None,
    version: int | None,
) -> ReceiptValidation:
    return ReceiptValidation(
        str(target),
        valid,
        receipt_id,
        created_at,
        operation,
        succeeded,
        reason,
        version,
    )


def validate_receipt_file(path: str | Path) -> ReceiptValidation:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _validation(target, False, None, None, None, None, f'Could not read receipt: {exc}', None)
    if not isinstance(data, dict):
        return _validation(target, False, None, None, None, None, 'Receipt JSON root is not an object.', None)

    receipt_id = data.get('receipt_id') if isinstance(data.get('receipt_id'), str) else None
    created_at = data.get('created_at') if isinstance(data.get('created_at'), str) else None
    operation = data.get('operation') if isinstance(data.get('operation'), str) else None
    succeeded = data.get('succeeded') if isinstance(data.get('succeeded'), bool) else None
    version_value = data.get('version')
    version = version_value if isinstance(version_value, int) and not isinstance(version_value, bool) else None
    if version not in SUPPORTED_RECEIPT_VERSIONS:
        return _validation(target, False, receipt_id, created_at, operation, succeeded, f'Unsupported receipt version {version_value!r}.', version)
    if not receipt_id or not created_at or not operation or succeeded is None:
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt identity fields are invalid.', version)
    if version >= 2 and data.get('verification') is not None and not isinstance(data.get('verification'), dict):
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt verification payload is invalid.', version)
    if receipt_id != _expected_receipt_id(data, version):
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt ID does not match its canonical identity content.', version)

    try:
        before = _observations(data.get('before'))
        after = _observations(data.get('after'))
    except ReceiptHistoryError as exc:
        return _validation(target, False, receipt_id, created_at, operation, succeeded, str(exc), version)
    expected_changes = [item.to_dict() for item in diff_project_state(before, after)]
    if data.get('changes') != expected_changes:
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt change list is inconsistent with before/after observations.', version)

    commands = data.get('commands')
    if not isinstance(commands, list):
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt command list is invalid.', version)
    computed_success = True
    for command in commands:
        if not isinstance(command, dict):
            return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt command record is invalid.', version)
        returncode = command.get('returncode')
        if returncode not in (None, 0):
            computed_success = False
    if computed_success != succeeded:
        return _validation(target, False, receipt_id, created_at, operation, succeeded, 'Receipt succeeded flag disagrees with command return codes.', version)
    return _validation(target, True, receipt_id, created_at, operation, succeeded, None, version)


def list_receipt_history(root: str | Path) -> list[ReceiptValidation]:
    root_path = Path(root).expanduser().resolve()
    directory = root_path / RECEIPT_DIRECTORY
    if not directory.is_dir():
        return []
    validations = [validate_receipt_file(path) for path in directory.glob('*.json') if path.is_file()]
    return sorted(validations, key=lambda item: (item.created_at or '', item.path))


def _load_after(path: str | Path) -> tuple[StateObservation, ...]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return _observations(data['after'])


def latest_receipt_drift(
    graph: ProjectGraph,
    *,
    extra_paths: Iterable[str | Path] = (),
) -> ReceiptDriftStatus:
    history = list_receipt_history(graph.root)
    if not history:
        return ReceiptDriftStatus('absent', None, (), (), 'No mutation receipts exist for this project.')
    invalid = tuple(item for item in history if not item.valid)
    valid_successes = [item for item in history if item.valid and item.succeeded]
    if not valid_successes:
        return ReceiptDriftStatus(
            'invalid' if invalid else 'no-successful-receipt',
            None,
            (),
            invalid,
            'No valid successful mutation receipt can be used as a current-state baseline.',
        )
    latest = valid_successes[-1]
    baseline = _load_after(latest.path)
    current = capture_project_state(graph, extra_paths=extra_paths)
    changes = tuple(item.to_dict() for item in diff_project_state(baseline, current) if item.status != 'unchanged')
    if invalid and history[-1] in invalid:
        return ReceiptDriftStatus(
            'invalid-latest-history', latest, changes, invalid,
            'A receipt newer than the latest valid successful baseline is invalid; history cannot be treated as continuous.',
        )
    if changes:
        return ReceiptDriftStatus(
            'drifted', latest, changes, invalid,
            'Current native project state differs from the latest valid successful mutation receipt.',
        )
    return ReceiptDriftStatus('current', latest, (), invalid)
