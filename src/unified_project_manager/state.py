from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import Finding, ProjectGraph

STATE_VERSION = 1
STATE_DIRECTORY = ".upm"
STATE_FILENAME = "state.json"


def state_path(root: Path) -> Path:
    return root / STATE_DIRECTORY / STATE_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def observed_files(graph: ProjectGraph) -> dict[str, dict[str, str]]:
    files: dict[str, dict[str, str]] = {}
    for component in graph.components:
        key = component.key(graph.root)
        for kind, names in (("manifest", component.manifests), ("lockfile", component.lockfiles)):
            for name in names:
                path = component.path / name
                if not path.is_file():
                    continue
                relative = path.relative_to(graph.root).as_posix()
                files[relative] = {"component": key, "kind": kind}
    return files


def build_state(graph: ProjectGraph) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for relative, metadata in sorted(observed_files(graph).items()):
        path = graph.root / relative
        files[relative] = {
            **metadata,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    return {
        "version": STATE_VERSION,
        "components": [
            {
                "key": component.key(graph.root),
                "ecosystem": component.ecosystem,
                "manager": component.manager,
            }
            for component in graph.components
        ],
        "files": files,
    }


def write_state(graph: ProjectGraph) -> Path:
    target = state_path(graph.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_state(graph), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def load_state(root: Path) -> dict[str, Any] | None:
    target = state_path(root)
    if not target.is_file():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("state root must be a JSON object")
    return data


def integrity_findings(graph: ProjectGraph) -> list[Finding]:
    target = state_path(graph.root)
    if not target.is_file():
        return []
    try:
        state = load_state(graph.root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return [Finding("state.invalid", "error", f"Could not read {STATE_DIRECTORY}/{STATE_FILENAME}: {exc}", hint="Regenerate it with 'upm snapshot'.")]
    assert state is not None

    if state.get("version") != STATE_VERSION:
        return [Finding("state.version-unsupported", "warning", f"State snapshot version {state.get('version')!r} is not supported by this UPM version.", hint="Regenerate it with 'upm snapshot'.")]

    recorded = state.get("files")
    if not isinstance(recorded, dict):
        return [Finding("state.invalid", "error", "State snapshot has no valid files table.", hint="Regenerate it with 'upm snapshot'.")]

    findings: list[Finding] = []
    current = observed_files(graph)
    for relative, entry in sorted(recorded.items()):
        if not isinstance(relative, str) or not isinstance(entry, dict):
            findings.append(Finding("state.invalid-entry", "warning", f"Ignoring invalid state entry for {relative!r}."))
            continue
        path = graph.root / relative
        component = entry.get("component") if isinstance(entry.get("component"), str) else None
        if not path.is_file():
            findings.append(Finding("state.file-missing", "error", f"Tracked {entry.get('kind', 'project')} file is missing: {relative}.", component, "Restore the file or accept the new project state with 'upm snapshot'."))
            continue
        expected = entry.get("sha256")
        if not isinstance(expected, str):
            findings.append(Finding("state.invalid-entry", "warning", f"No valid checksum is recorded for {relative}.", component))
            continue
        actual = _sha256(path)
        if actual != expected:
            findings.append(Finding("state.file-changed", "warning", f"Tracked file changed since the last snapshot: {relative}.", component, "Review the change, then run 'upm snapshot' to accept it."))

    for relative, metadata in sorted(current.items()):
        if relative not in recorded:
            findings.append(Finding("state.file-untracked", "info", f"New {metadata['kind']} is not present in the integrity snapshot: {relative}.", metadata["component"], "Run 'upm snapshot' after reviewing the new project state."))

    return findings
