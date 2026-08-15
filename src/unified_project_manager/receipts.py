from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import ProjectGraph

RECEIPT_VERSION = 2
SUPPORTED_RECEIPT_VERSIONS = frozenset({1, RECEIPT_VERSION})
RECEIPT_DIRECTORY = Path('.upm/receipts')
_REDACTED = '<redacted>'
_SENSITIVE_FLAG = re.compile(r'(?i)(token|password|passwd|secret|credential|auth(?:entication)?(?:-?token)?)')
_SENSITIVE_ASSIGNMENT = re.compile(r'(?i)(token|password|passwd|secret|_?auth(?:token)?|credential)=')


@dataclass(frozen=True)
class StateObservation:
    path: str
    kind: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateChange:
    path: str
    kind: str
    status: str
    before_sha256: str | None
    after_sha256: str | None
    before_size: int | None
    after_size: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReceiptCommand:
    component: str | None
    manager: str | None
    cwd: str
    argv: tuple[str, ...]
    returncode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['argv'] = list(self.argv)
        return data


@dataclass(frozen=True)
class MutationReceipt:
    version: int
    receipt_id: str
    created_at: str
    operation: str
    commands: tuple[ReceiptCommand, ...]
    before: tuple[StateObservation, ...]
    after: tuple[StateObservation, ...]
    changes: tuple[StateChange, ...]
    verification: Mapping[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return all(command.returncode in (None, 0) for command in self.commands)

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'receipt_id': self.receipt_id,
            'created_at': self.created_at,
            'operation': self.operation,
            'succeeded': self.succeeded,
            'commands': [command.to_dict() for command in self.commands],
            'before': [item.to_dict() for item in self.before],
            'after': [item.to_dict() for item in self.after],
            'changes': [item.to_dict() for item in self.changes],
            'verification': dict(self.verification) if self.verification is not None else None,
        }


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    redact_next = False
    for raw in argv:
        item = str(raw)
        if redact_next:
            result.append(_REDACTED)
            redact_next = False
            continue
        if item.startswith('-') and '=' not in item and _SENSITIVE_FLAG.search(item):
            result.append(item)
            redact_next = True
            continue
        if _SENSITIVE_ASSIGNMENT.search(item):
            key = item.split('=', 1)[0]
            result.append(f'{key}={_REDACTED}')
            continue
        result.append(item)
    return tuple(result)


def _digest(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size


def capture_project_state(
    graph: ProjectGraph,
    *,
    extra_paths: Iterable[str | Path] = (),
) -> tuple[StateObservation, ...]:
    candidates: dict[Path, str] = {}
    for component in graph.components:
        for name in component.manifests:
            candidates[(component.path / name).resolve()] = 'manifest'
        for name in component.lockfiles:
            candidates[(component.path / name).resolve()] = 'native-state'
    for value in extra_paths:
        path = Path(value)
        if not path.is_absolute():
            path = graph.root / path
        candidates[path.resolve()] = 'extra-native-state'

    observations: list[StateObservation] = []
    for path, kind in candidates.items():
        try:
            relative = path.relative_to(graph.root).as_posix()
        except ValueError as exc:
            raise ValueError(f'Receipt state path escapes the project root: {path}') from exc
        if not path.is_file() or path.is_symlink():
            continue
        digest, size = _digest(path)
        observations.append(StateObservation(relative, kind, digest, size))
    return tuple(sorted(observations, key=lambda item: (item.path, item.kind)))


def diff_project_state(
    before: Sequence[StateObservation],
    after: Sequence[StateObservation],
) -> tuple[StateChange, ...]:
    before_map = {item.path: item for item in before}
    after_map = {item.path: item for item in after}
    changes: list[StateChange] = []
    for path in sorted(set(before_map) | set(after_map)):
        old = before_map.get(path)
        new = after_map.get(path)
        if old is None:
            status = 'added'
        elif new is None:
            status = 'removed'
        elif old.sha256 != new.sha256 or old.size != new.size:
            status = 'changed'
        else:
            status = 'unchanged'
        kind = new.kind if new is not None else old.kind  # type: ignore[union-attr]
        changes.append(StateChange(
            path=path,
            kind=kind,
            status=status,
            before_sha256=old.sha256 if old else None,
            after_sha256=new.sha256 if new else None,
            before_size=old.size if old else None,
            after_size=new.size if new else None,
        ))
    return tuple(changes)


def _normalize_command(root: Path, value: Mapping[str, Any]) -> ReceiptCommand:
    cwd_value = value.get('cwd', '.')
    cwd = Path(str(cwd_value))
    if cwd.is_absolute():
        try:
            cwd_text = cwd.resolve().relative_to(root).as_posix() or '.'
        except ValueError:
            cwd_text = '<outside-project>'
    else:
        cwd_text = cwd.as_posix() or '.'
    argv = value.get('argv', ())
    if not isinstance(argv, (list, tuple)):
        raise ValueError('Receipt command argv must be a sequence.')
    return ReceiptCommand(
        component=str(value['component']) if value.get('component') is not None else None,
        manager=str(value['manager']) if value.get('manager') is not None else None,
        cwd=cwd_text,
        argv=redact_argv([str(item) for item in argv]),
        returncode=value.get('returncode') if isinstance(value.get('returncode'), int) else None,
    )


def receipt_identity_payload(
    *,
    version: int,
    operation: Any,
    commands: Any,
    before: Any,
    after: Any,
    created_at: Any,
    verification: Any = None,
) -> dict[str, Any]:
    """Return the canonical fields bound by a receipt ID for a schema version.

    v1 is retained only for backwards-readable validation. v2 additionally binds
    the persisted post-operation verification payload and the schema version itself.
    Derived fields such as `changes` and `succeeded` are recomputed from bound
    before/after/command state and therefore are not independently hashed.
    """
    stable = {
        'operation': operation,
        'commands': commands,
        'before': before,
        'after': after,
        'created_at': created_at,
    }
    if version >= 2:
        stable = {
            'version': version,
            **stable,
            'verification': verification,
        }
    return stable


def receipt_identity_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def build_mutation_receipt(
    root: str | Path,
    operation: str,
    commands: Iterable[Mapping[str, Any]],
    before: Sequence[StateObservation],
    after: Sequence[StateObservation],
    *,
    verification: Mapping[str, Any] | None = None,
    created: datetime | None = None,
) -> MutationReceipt:
    root_path = Path(root).expanduser().resolve()
    command_list = tuple(_normalize_command(root_path, value) for value in commands)
    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    created_at = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    changes = diff_project_state(before, after)
    stable = receipt_identity_payload(
        version=RECEIPT_VERSION,
        operation=operation,
        commands=[command.to_dict() for command in command_list],
        before=[item.to_dict() for item in before],
        after=[item.to_dict() for item in after],
        created_at=created_at,
        verification=dict(verification) if verification is not None else None,
    )
    digest = receipt_identity_digest(stable)
    return MutationReceipt(
        version=RECEIPT_VERSION,
        receipt_id=digest,
        created_at=created_at,
        operation=operation,
        commands=command_list,
        before=tuple(before),
        after=tuple(after),
        changes=changes,
        verification=verification,
    )


def write_mutation_receipt(
    root: str | Path,
    receipt: MutationReceipt,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    if path is None:
        safe_time = receipt.created_at.replace(':', '').replace('-', '').replace('+', '').replace('Z', 'Z')
        target = root_path / RECEIPT_DIRECTORY / f'{safe_time}-{receipt.receipt_id[:12]}.json'
    else:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = root_path / target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target
