from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

EVIDENCE_MANIFEST_VERSION = 1
DEFAULT_EVIDENCE_MANIFEST_PATH = Path('.upm/evidence-manifest.json')


class EvidenceManifestError(ValueError):
    """Raised when a project evidence manifest cannot be built or validated safely."""


@dataclass(frozen=True)
class EvidenceArtifact:
    path: str
    kind: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceManifest:
    version: int
    generated_at: str
    evidence_set_id: str
    artifacts: tuple[EvidenceArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'generated_at': self.generated_at,
            'evidence_set_id': self.evidence_set_id,
            'artifacts': [item.to_dict() for item in self.artifacts],
        }


@dataclass(frozen=True)
class EvidenceManifestValidation:
    valid: bool
    evidence_set_id: str | None
    missing: tuple[str, ...]
    changed: tuple[str, ...]
    unexpected: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'valid': self.valid,
            'evidence_set_id': self.evidence_set_id,
            'missing': list(self.missing),
            'changed': list(self.changed),
            'unexpected': list(self.unexpected),
            'reason': self.reason,
            'authenticated': False,
        }


def _sha256_file(path: Path) -> tuple[str, int]:
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


def _relative_file(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceManifestError(f'Evidence path escapes project root: {resolved}') from exc
    if path.is_symlink():
        raise EvidenceManifestError(f'Refusing symlinked evidence artifact: {relative.as_posix()}')
    return relative.as_posix()


def _known_evidence_paths(root: Path) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    fixed = (
        (Path('.upm/state.json'), 'integrity-snapshot'),
        (Path('.upm/audits/osv.json'), 'advisory-evidence-legacy'),
        (Path('.upm/audits/osv-v2.json'), 'advisory-evidence-v2'),
        (Path('.upm/receipt-chain.json'), 'receipt-chain'),
    )
    for relative, kind in fixed:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            candidates.append((path, kind))

    receipt_directory = root / '.upm/receipts'
    if receipt_directory.is_dir() and not receipt_directory.is_symlink():
        for path in sorted(receipt_directory.glob('*.json')):
            if path.is_file() and not path.is_symlink():
                candidates.append((path, 'mutation-receipt'))
    return candidates


def _identity_payload(artifacts: Iterable[EvidenceArtifact]) -> dict[str, Any]:
    return {
        'version': EVIDENCE_MANIFEST_VERSION,
        'artifacts': [item.to_dict() for item in artifacts],
    }


def _identity_digest(artifacts: Iterable[EvidenceArtifact]) -> str:
    payload = _identity_payload(artifacts)
    rendered = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(rendered).hexdigest()


def build_evidence_manifest(
    root: str | Path,
    *,
    created: datetime | None = None,
) -> EvidenceManifest:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise EvidenceManifestError(f'Project root is not a directory: {root_path}')

    artifacts: list[EvidenceArtifact] = []
    for path, kind in _known_evidence_paths(root_path):
        relative = _relative_file(root_path, path)
        digest, size = _sha256_file(path)
        artifacts.append(EvidenceArtifact(relative, kind, digest, size))
    artifacts.sort(key=lambda item: (item.path, item.kind))

    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    artifact_tuple = tuple(artifacts)
    return EvidenceManifest(
        EVIDENCE_MANIFEST_VERSION,
        generated_at,
        _identity_digest(artifact_tuple),
        artifact_tuple,
    )


def canonical_manifest_bytes(manifest: EvidenceManifest | dict[str, Any]) -> bytes:
    data = manifest.to_dict() if isinstance(manifest, EvidenceManifest) else manifest
    stable = {
        'version': data.get('version'),
        'evidence_set_id': data.get('evidence_set_id'),
        'artifacts': data.get('artifacts'),
    }
    return (json.dumps(stable, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def evidence_manifest_anchor_digest(manifest: EvidenceManifest | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def write_evidence_manifest(
    root: str | Path,
    manifest: EvidenceManifest,
    path: str | Path | None = None,
) -> Path:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_EVIDENCE_MANIFEST_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise EvidenceManifestError(f'Evidence manifest path escapes project root: {target}') from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(target)
    return target


def _parse_artifacts(values: object) -> tuple[EvidenceArtifact, ...]:
    if not isinstance(values, list):
        raise EvidenceManifestError('Evidence manifest artifacts must be an array.')
    result: list[EvidenceArtifact] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise EvidenceManifestError('Evidence manifest artifact is not an object.')
        path = value.get('path')
        kind = value.get('kind')
        digest = value.get('sha256')
        size = value.get('size')
        if not all(isinstance(item, str) and item for item in (path, kind, digest)):
            raise EvidenceManifestError('Evidence manifest artifact identity is invalid.')
        if path in seen:
            raise EvidenceManifestError(f'Evidence manifest artifact path appears more than once: {path}')
        if Path(path).is_absolute() or '..' in Path(path).parts:
            raise EvidenceManifestError(f'Evidence manifest artifact path is not project-relative: {path}')
        if len(digest) != 64:
            raise EvidenceManifestError(f'Evidence manifest SHA-256 is invalid for {path}.')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise EvidenceManifestError(f'Evidence manifest size is invalid for {path}.')
        seen.add(path)
        result.append(EvidenceArtifact(path, kind, digest, size))
    return tuple(sorted(result, key=lambda item: (item.path, item.kind)))


def validate_evidence_manifest(
    root: str | Path,
    manifest: EvidenceManifest | dict[str, Any],
) -> EvidenceManifestValidation:
    root_path = Path(root).expanduser().resolve()
    data = manifest.to_dict() if isinstance(manifest, EvidenceManifest) else manifest
    try:
        if data.get('version') != EVIDENCE_MANIFEST_VERSION:
            raise EvidenceManifestError(
                f'Unsupported evidence manifest version {data.get("version")!r}.'
            )
        evidence_set_id = data.get('evidence_set_id')
        if not isinstance(evidence_set_id, str) or len(evidence_set_id) != 64:
            raise EvidenceManifestError('Evidence manifest evidence_set_id is invalid.')
        artifacts = _parse_artifacts(data.get('artifacts'))
        if _identity_digest(artifacts) != evidence_set_id:
            raise EvidenceManifestError('Evidence manifest ID does not match its artifact table.')
    except EvidenceManifestError as exc:
        return EvidenceManifestValidation(False, None, (), (), (), str(exc))

    expected = {item.path: item for item in artifacts}
    current_manifest = build_evidence_manifest(root_path)
    current = {item.path: item for item in current_manifest.artifacts}
    missing = tuple(sorted(set(expected) - set(current)))
    unexpected = tuple(sorted(set(current) - set(expected)))
    changed = tuple(sorted(
        path
        for path in set(expected) & set(current)
        if expected[path].sha256 != current[path].sha256
        or expected[path].size != current[path].size
        or expected[path].kind != current[path].kind
    ))
    valid = not missing and not unexpected and not changed
    reason = None if valid else 'Current local evidence artifacts do not exactly match the anchored evidence manifest.'
    return EvidenceManifestValidation(valid, evidence_set_id, missing, changed, unexpected, reason)


def load_evidence_manifest(
    root: str | Path,
    path: str | Path | None = None,
) -> EvidenceManifestValidation:
    root_path = Path(root).expanduser().resolve()
    target = root_path / DEFAULT_EVIDENCE_MANIFEST_PATH if path is None else Path(path).expanduser()
    if not target.is_absolute():
        target = (root_path / target).resolve()
    if not target.is_file():
        return EvidenceManifestValidation(False, None, (), (), (), 'No evidence manifest exists.')
    try:
        value = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return EvidenceManifestValidation(False, None, (), (), (), f'Could not read evidence manifest: {exc}')
    if not isinstance(value, dict):
        return EvidenceManifestValidation(False, None, (), (), (), 'Evidence manifest JSON root is not an object.')
    return validate_evidence_manifest(root_path, value)
