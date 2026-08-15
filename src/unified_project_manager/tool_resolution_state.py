from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tool_resolution import ToolResolutionReport

TOOL_RESOLUTION_STATE_VERSION = 2
DEFAULT_TOOL_RESOLUTION_STATE_PATH = Path('.upm/tools.json')


class ToolResolutionStateError(ValueError):
    """Raised when a machine-local tool resolution baseline is invalid."""


@dataclass(frozen=True)
class ToolResolutionStateObservation:
    component: str
    role: str
    name: str
    requirement: str | None
    resolved_path: str | None
    available: bool
    version: str | None
    version_returncode: int | None

    @property
    def key(self) -> str:
        return '\0'.join((self.component, self.role, self.name))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResolutionStateSnapshot:
    version: int
    state_id: str
    generated_at: str
    portable: bool
    version_probes_executed: bool
    observations: tuple[ToolResolutionStateObservation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'state_id': self.state_id,
            'generated_at': self.generated_at,
            'portable': self.portable,
            'version_probes_executed': self.version_probes_executed,
            'observations': [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True)
class ToolResolutionStateChange:
    code: str
    component: str
    role: str
    name: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResolutionStateStatus:
    state: str
    baseline_state_id: str | None
    current_state_id: str | None
    version_probes_executed: bool
    changes: tuple[ToolResolutionStateChange, ...]
    reason: str | None = None

    @property
    def current(self) -> bool:
        return self.state == 'current'

    def to_dict(self) -> dict[str, Any]:
        return {
            'state': self.state,
            'current': self.current,
            'baseline_state_id': self.baseline_state_id,
            'current_state_id': self.current_state_id,
            'version_probes_executed': self.version_probes_executed,
            'changes': [item.to_dict() for item in self.changes],
            'reason': self.reason,
            'portable': False,
        }


def _observations(report: ToolResolutionReport) -> tuple[ToolResolutionStateObservation, ...]:
    return tuple(sorted((
        ToolResolutionStateObservation(
            component=item.component,
            role=item.role,
            name=item.name,
            requirement=item.requirement,
            resolved_path=item.resolved_path,
            available=item.available,
            version=item.version if report.version_probes_executed else None,
            version_returncode=item.version_returncode if report.version_probes_executed else None,
        )
        for item in report.observations
    ), key=lambda item: (item.component, item.role, item.name)))


def _identity(
    observations: tuple[ToolResolutionStateObservation, ...],
    *,
    version_probes_executed: bool,
) -> str:
    payload = {
        'version': TOOL_RESOLUTION_STATE_VERSION,
        'portable': False,
        'version_probes_executed': version_probes_executed,
        'observations': [item.to_dict() for item in observations],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()


def build_tool_resolution_state(
    report: ToolResolutionReport,
    *,
    created: datetime | None = None,
) -> ToolResolutionStateSnapshot:
    observations = _observations(report)
    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return ToolResolutionStateSnapshot(
        TOOL_RESOLUTION_STATE_VERSION,
        _identity(observations, version_probes_executed=report.version_probes_executed),
        generated_at,
        False,
        report.version_probes_executed,
        observations,
    )


def write_tool_resolution_state(
    root: str | Path,
    snapshot: ToolResolutionStateSnapshot,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_TOOL_RESOLUTION_STATE_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ToolResolutionStateError(f'Tool resolution state path escapes project root: {target}') from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def _parse_observation(value: object) -> ToolResolutionStateObservation:
    if not isinstance(value, dict):
        raise ToolResolutionStateError('Tool resolution state observation is not an object.')
    component = value.get('component')
    role = value.get('role')
    name = value.get('name')
    requirement = value.get('requirement')
    resolved_path = value.get('resolved_path')
    available = value.get('available')
    version = value.get('version')
    returncode = value.get('version_returncode')
    if not all(isinstance(item, str) and item for item in (component, role, name)):
        raise ToolResolutionStateError('Tool resolution state observation identity is invalid.')
    if requirement is not None and not isinstance(requirement, str):
        raise ToolResolutionStateError('Tool resolution requirement must be string or null.')
    if resolved_path is not None and not isinstance(resolved_path, str):
        raise ToolResolutionStateError('Tool resolution path must be string or null.')
    if not isinstance(available, bool):
        raise ToolResolutionStateError('Tool resolution availability must be boolean.')
    if version is not None and not isinstance(version, str):
        raise ToolResolutionStateError('Tool resolution version must be string or null.')
    if returncode is not None and (not isinstance(returncode, int) or isinstance(returncode, bool)):
        raise ToolResolutionStateError('Tool resolution probe return code must be integer or null.')
    return ToolResolutionStateObservation(
        component, role, name, requirement, resolved_path, available, version, returncode
    )


def load_tool_resolution_state(
    root: str | Path,
    path: str | Path | None = None,
) -> ToolResolutionStateSnapshot | None:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_TOOL_RESOLUTION_STATE_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolResolutionStateError(f'Could not read tool resolution state: {exc}') from exc
    if not isinstance(data, dict) or data.get('version') != TOOL_RESOLUTION_STATE_VERSION:
        raise ToolResolutionStateError(
            'Unsupported tool resolution baseline schema. Recreate it with the execution-safe v2 baseline command.'
        )
    if data.get('portable') is not False:
        raise ToolResolutionStateError('Tool resolution state must declare portable=false.')
    probes = data.get('version_probes_executed')
    if not isinstance(probes, bool):
        raise ToolResolutionStateError('Tool resolution state must declare whether version probes were executed.')
    state_id = data.get('state_id')
    generated_at = data.get('generated_at')
    values = data.get('observations')
    if not isinstance(state_id, str) or len(state_id) != 64:
        raise ToolResolutionStateError('Tool resolution state_id is invalid.')
    if not isinstance(generated_at, str) or not generated_at:
        raise ToolResolutionStateError('Tool resolution generated_at is invalid.')
    if not isinstance(values, list):
        raise ToolResolutionStateError('Tool resolution observations must be an array.')
    observations = tuple(sorted(
        (_parse_observation(item) for item in values),
        key=lambda item: (item.component, item.role, item.name),
    ))
    if len({item.key for item in observations}) != len(observations):
        raise ToolResolutionStateError('Tool resolution state contains duplicate component/role/name observations.')
    if not probes and any(item.version is not None or item.version_returncode is not None for item in observations):
        raise ToolResolutionStateError('Path-only tool baseline contains version-probe evidence.')
    if _identity(observations, version_probes_executed=probes) != state_id:
        raise ToolResolutionStateError('Tool resolution state ID does not match its observation table.')
    return ToolResolutionStateSnapshot(
        TOOL_RESOLUTION_STATE_VERSION,
        state_id,
        generated_at,
        False,
        probes,
        observations,
    )


def compare_tool_resolution_state(
    baseline: ToolResolutionStateSnapshot | None,
    current: ToolResolutionReport | None,
) -> ToolResolutionStateStatus:
    if baseline is None:
        return ToolResolutionStateStatus(
            'absent', None, None, False, (), 'No machine-local tool resolution baseline exists.'
        )
    if current is None:
        return ToolResolutionStateStatus(
            'probe-required' if baseline.version_probes_executed else 'current-resolution-required',
            baseline.state_id,
            None,
            baseline.version_probes_executed,
            (),
            (
                'This baseline includes explicit version-probe evidence; re-run the check with --probe-versions to execute matching probes.'
                if baseline.version_probes_executed
                else 'Current path resolution has not been collected.'
            ),
        )
    if current.version_probes_executed != baseline.version_probes_executed:
        return ToolResolutionStateStatus(
            'mode-mismatch',
            baseline.state_id,
            None,
            current.version_probes_executed,
            (),
            'Current tool resolution mode does not match the baseline version-probe mode.',
        )

    current_snapshot = build_tool_resolution_state(current)
    old = {item.key: item for item in baseline.observations}
    new = {item.key: item for item in current_snapshot.observations}
    changes: list[ToolResolutionStateChange] = []
    fields = [
        ('tool-requirement-changed', 'requirement'),
        ('tool-path-changed', 'resolved_path'),
        ('tool-availability-changed', 'available'),
    ]
    if baseline.version_probes_executed:
        fields.extend((
            ('tool-version-changed', 'version'),
            ('tool-version-probe-changed', 'version_returncode'),
        ))

    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)
        identity = after or before
        assert identity is not None
        if before is None:
            changes.append(ToolResolutionStateChange(
                'tool-observation-added', identity.component, identity.role, identity.name, None, after.to_dict()
            ))
            continue
        if after is None:
            changes.append(ToolResolutionStateChange(
                'tool-observation-removed', identity.component, identity.role, identity.name, before.to_dict(), None
            ))
            continue
        for code, field in fields:
            before_value = getattr(before, field)
            after_value = getattr(after, field)
            if before_value != after_value:
                changes.append(ToolResolutionStateChange(
                    code, identity.component, identity.role, identity.name, before_value, after_value
                ))

    if changes:
        return ToolResolutionStateStatus(
            'drifted',
            baseline.state_id,
            current_snapshot.state_id,
            baseline.version_probes_executed,
            tuple(changes),
            'Current manager/toolchain resolution differs from the machine-local baseline.',
        )
    return ToolResolutionStateStatus(
        'current', baseline.state_id, current_snapshot.state_id,
        baseline.version_probes_executed, (), None
    )
