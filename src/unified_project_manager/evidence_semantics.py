from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .advisory_evidence_v2 import load_advisory_evidence_v2
from .evidence_manifest import EvidenceManifestValidation, load_evidence_manifest
from .receipt_chain import validate_receipt_chain
from .receipt_history import validate_receipt_file
from .state import load_state


@dataclass(frozen=True)
class EvidenceSemanticCheck:
    path: str
    kind: str
    assurance: str
    valid: bool | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectEvidenceValidation:
    valid: bool
    manifest: EvidenceManifestValidation
    semantic_checks: tuple[EvidenceSemanticCheck, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'valid': self.valid,
            'manifest': self.manifest.to_dict(),
            'semantic_checks': [item.to_dict() for item in self.semantic_checks],
            'reason': self.reason,
            'authenticated': False,
        }


def _manifest_artifacts(root: Path) -> list[dict[str, Any]]:
    path = root / '.upm/evidence-manifest.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    artifacts = value.get('artifacts') if isinstance(value, dict) else None
    return [item for item in artifacts if isinstance(item, dict)] if isinstance(artifacts, list) else []


def _validate_snapshot(root: Path, relative: str) -> EvidenceSemanticCheck:
    if relative != '.upm/state.json':
        return EvidenceSemanticCheck(relative, 'integrity-snapshot', 'schema-readability', False, 'Unexpected integrity snapshot path.')
    try:
        state = load_state(root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return EvidenceSemanticCheck(relative, 'integrity-snapshot', 'schema-readability', False, str(exc))
    if not isinstance(state, dict):
        return EvidenceSemanticCheck(relative, 'integrity-snapshot', 'schema-readability', False, 'Integrity snapshot root is not an object.')
    version = state.get('version')
    if not isinstance(version, int) or isinstance(version, bool):
        return EvidenceSemanticCheck(relative, 'integrity-snapshot', 'schema-readability', False, 'Integrity snapshot has no valid version.')
    return EvidenceSemanticCheck(relative, 'integrity-snapshot', 'schema-readability', True)


def validate_project_evidence(root: str | Path) -> ProjectEvidenceValidation:
    root_path = Path(root).expanduser().resolve()
    manifest = load_evidence_manifest(root_path)
    if not manifest.valid:
        return ProjectEvidenceValidation(
            False,
            manifest,
            (),
            'Evidence manifest byte-set validation failed; semantic validation was not attempted.',
        )

    checks: list[EvidenceSemanticCheck] = []
    for artifact in _manifest_artifacts(root_path):
        relative = artifact.get('path')
        kind = artifact.get('kind')
        if not isinstance(relative, str) or not isinstance(kind, str):
            checks.append(EvidenceSemanticCheck(str(relative), str(kind), 'manifest-schema', False, 'Artifact identity is invalid.'))
            continue
        path = root_path / relative

        if kind == 'advisory-evidence-v2':
            validation = load_advisory_evidence_v2(root_path, path=path)
            checks.append(EvidenceSemanticCheck(
                relative,
                kind,
                'self-validating-v2',
                validation.valid,
                validation.reason,
            ))
            continue

        if kind == 'advisory-evidence-legacy':
            checks.append(EvidenceSemanticCheck(
                relative,
                kind,
                'hash-bound-compatibility',
                None,
                'Legacy advisory evidence is byte-bound by the manifest but is not upgraded to v2 semantic guarantees.',
            ))
            continue

        if kind == 'mutation-receipt':
            validation = validate_receipt_file(path)
            assurance = (
                'receipt-v2-verification-bound'
                if validation.version == 2
                else 'receipt-v1-legacy-readable'
            )
            checks.append(EvidenceSemanticCheck(
                relative,
                kind,
                assurance,
                validation.valid,
                validation.reason,
            ))
            continue

        if kind == 'receipt-chain':
            validation = validate_receipt_chain(root_path, path=path)
            checks.append(EvidenceSemanticCheck(
                relative,
                kind,
                'receipt-chain-exact-v2-identities',
                validation.valid,
                validation.reason,
            ))
            continue

        if kind == 'integrity-snapshot':
            checks.append(_validate_snapshot(root_path, relative))
            continue

        checks.append(EvidenceSemanticCheck(
            relative,
            kind,
            'unknown',
            False,
            f'No semantic validator is configured for evidence kind {kind!r}.',
        ))

    invalid = [item for item in checks if item.valid is False]
    valid = not invalid
    reason = None if valid else 'One or more byte-anchored evidence artifacts failed semantic validation.'
    return ProjectEvidenceValidation(valid, manifest, tuple(checks), reason)
