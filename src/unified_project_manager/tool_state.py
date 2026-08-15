from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tool_inventory import ToolInventory

TOOL_STATE_VERSION = 1
DEFAULT_TOOL_STATE_PATH = Path('.upm/tools.json')


class ToolStateError(ValueError):
    """Raised when a machine-local tool state baseline is invalid."""


@dataclass(frozen=True)
class ToolStateObservation:
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
class ToolStateSnapshot:
    version: int
    state_id: str
    generated_at: str
    portable: bool
    observations: tuple[ToolStateObservation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'state_id': self.state_id,
            'generated_at': self.generated_at,
            'portable': self.portable,
            'observations': [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True)
class ToolStateChange:
    code: str
    component: str
    role: str
    name: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolStateStatus:
    state: str
    valid_baseline: bool
    baseline_state_id: str | None
    current_state_id: str | None
    changes: tuple[ToolStateChange, ...]
    reason: str | None = None

    @property
    def current(self) -> bool:
        return self.state == 'current'

    def to_dict(self) -> dict[str, Any]:
        return {
            'state': self.state,
            'current': self.current,
            'valid_baseline': self.valid_baseline,
            'baseline_state_id': self.baseline_state_id,
            'current_state_id': self.current_state_id,
            'changes': [item.to_dict() for item in self.changes],
            'reason': self.reason,
            'portable': False,
        }


def _observations(inventory: ToolInventory) -> tuple[ToolStateObservation, ...]:
    values = tuple(sorted((
        ToolStateObservation(
            component=item.component,
            role=item.role,
            name=item.name,
            requirement=item.requirement,
            resolved_path=item.resolved_path,
            available=item.available,
            version=item.version,
            version_returncode=item.version_returncode,
        )
        for item in inventory.resolutions
    ), key=lambda item: (item.component, item.role, item.name)))
    return values


def _identity(observations: tuple[ToolStateObservation, ...]) -> str:
    payload = {
        'version': TOOL_STATE_VERSION,
        'portable': False,
        'observations': [item.to_dict() for item in observations],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def build_tool_state(
    inventory: ToolInventory,
    *,
    created: datetime | None = None,
) -> ToolStateSnapshot:
    observations = _observations(inventory)
    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return ToolStateSnapshot(
        TOOL_STATE_VERSION,
        _identity(observations),
        generated_at,
        False,
        observations,
    )


def write_tool_state(
    root: str | Path,
    snapshot: ToolStateSnapshot,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_TOOL_STATE_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ToolStateError(f'Tool state path escapes project root: {target}') from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def _parse_observation(value: object) -> ToolStateObservation:
    if not isinstance(value, dict):
        raise ToolStateError('Tool state observation is not an object.')
    component = value.get('component')
    role = value.get('role')
    name = value.get('name')
    requirement = value.get('requirement')
    resolved_path = value.get('resolved_path')
    available = value.get('available')
    version = value.get('version')
    returncode = value.get('version_returncode')
    if not all(isinstance(item, str) and item for item in (component, role, name)):
        raise ToolStateError('Tool state observation identity is invalid.')
    if requirement is not None and not isinstance(requirement, str):
        raise ToolStateError('Tool state requirement must be a string or null.')
    if resolved_path is not None and not isinstance(resolved_path, str):
        raise ToolStateError('Tool state resolved_path must be a string or null.')
    if not isinstance(available, bool):
        raise ToolStateError('Tool state available must be boolean.')
    if version is not None and not isinstance(version, str):
        raise ToolStateError('Tool state version must be a string or null.')
    if returncode is not None and (not isinstance(returncode, int) or isinstance(returncode, bool)):
        raise ToolStateError('Tool state version_returncode must be integer or null.')
    return ToolStateObservation(component, role, name, requirement, resolved_path, available, version, returncode)


def load_tool_state(root: str | Path, path: str | Path | None = None) -> ToolStateSnapshot | None:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_TOOL_STATE_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolStateError(f'Could not read tool state: {exc}') from exc
    if not isinstance(data, dict) or data.get('version') != TOOL_STATE_VERSION:
        raise ToolStateError('Unsupported or invalid tool state schema.')
    if data.get('portable') is not False:
        raise ToolStateError('Tool state must declare portable=false.')
    state_id = data.get('state_id')
    generated_at = data.get('generated_at')
    values = data.get('observations')
    if not isinstance(state_id, str) or len(state_id) != 64:
        raise ToolStateError('Tool state state_id is invalid.')
    if not isinstance(generated_at, str) or not generated_at:
        raise ToolStateError('Tool state generated_at is invalid.')
    if not isinstance(values, list):
        raise ToolStateError('Tool state observations must be an array.')
    observations = tuple(sorted((_parse_observation(item) for item in values), key=lambda item: (item.component, item.role, item.name)))
    if len({item.key for item in observations}) != len(observations):
        raise ToolStateError('Tool state contains duplicate component/role/name observations.')
    if _identity(observations) != state_id:
        raise ToolStateError('Tool state ID does not match its observation table.')
    return ToolStateSnapshot(TOOL_STATE_VERSION, state_id, generated_at, False, observations)


def compare_tool_state(
    baseline: ToolStateSnapshot | None,
    current_inventory: ToolInventory,
) -> ToolStateStatus:
    current = build_tool_state(current_inventory)
    if baseline is None:
        return ToolStateStatus(
            'absent',
            False,
            None,
            current.state_id,
            (),
            'No machine-local tool baseline exists.',
        )

    old = {item.key: item for item in baseline.observations}
    new = {item.key: item for item in current.observations}
    changes: list[ToolStateChange] = []

    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)
        identity = after or before
        assert identity is not None
        if before is None:
            changes.append(ToolStateChange('tool-observation-added', identity.component, identity.role, identity.name, None, after.to_dict()))
            continue
        if after is None:
            changes.append(ToolStateChange('tool-observation-removed', identity.component, identity.role, identity.name, before.to_dict(), None))
            continue
        fields = (
            ('tool-requirement-changed', 'requirement'),
            ('tool-path-changed', 'resolved_path'),
            ('tool-availability-changed', 'available'),
            ('tool-version-changed', 'version'),
            ('tool-version-probe-changed', 'version_returncode'),
        )
        for code, field in fields:
            old_value = getattr(before, field)
            new_value = getattr(after, field)
            if old_value != new_value:
                changes.append(ToolStateChange(code, identity.component, identity.role, identity.name, old_value, new_value))

    if changes:
        return ToolStateStatus(
            'drifted',
            True,
            baseline.state_id,
            current.state_id,
            tuple(changes),
            'Current manager/toolchain resolution differs from the machine-local baseline.',
        )
    return ToolStateStatus('current', True, baseline.state_id, current.state_id, ())
