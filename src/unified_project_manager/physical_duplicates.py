from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ProjectGraph


@dataclass(frozen=True)
class ArtifactRoot:
    path: Path
    category: str
    components: tuple[str, ...]


@dataclass(frozen=True)
class PhysicalInstance:
    size: int
    paths: tuple[str, ...]
    categories: tuple[str, ...]
    components: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhysicalDuplicateGroup:
    sha256: str
    size: int
    physical_instances: tuple[PhysicalInstance, ...]
    duplicate_content_bytes: int
    reclaimable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "size": self.size,
            "physical_instances": [item.to_dict() for item in self.physical_instances],
            "duplicate_content_bytes": self.duplicate_content_bytes,
            "reclaimable": self.reclaimable,
        }


@dataclass(frozen=True)
class HardlinkObservation:
    size: int
    paths: tuple[str, ...]
    categories: tuple[str, ...]
    components: tuple[str, ...]
    shared_physical_bytes: bool = True
    duplicate_content_bytes: int = 0
    reclaimable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhysicalDuplicateReport:
    groups: tuple[PhysicalDuplicateGroup, ...]
    hardlinks: tuple[HardlinkObservation, ...]
    artifact_roots: tuple[dict[str, Any], ...]
    files_considered: int
    physical_files_considered: int
    bytes_hashed: int
    min_size_bytes: int
    skipped: tuple[str, ...]

    @property
    def duplicate_content_bytes(self) -> int:
        return sum(group.duplicate_content_bytes for group in self.groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "groups": [item.to_dict() for item in self.groups],
            "hardlinks": [item.to_dict() for item in self.hardlinks],
            "artifact_roots": list(self.artifact_roots),
            "summary": {
                "groups": len(self.groups),
                "hardlink_groups": len(self.hardlinks),
                "files_considered": self.files_considered,
                "physical_files_considered": self.physical_files_considered,
                "bytes_hashed": self.bytes_hashed,
                "duplicate_content_bytes": self.duplicate_content_bytes,
                "min_size_bytes": self.min_size_bytes,
            },
            "skipped": list(self.skipped),
            "reclaimable": False,
            "network_executed": False,
            "mutation_executed": False,
        }


@dataclass
class _InodeRecord:
    size: int
    paths: set[str]
    categories: set[str]
    components: set[str]
    source_path: Path


def known_artifact_roots(graph: ProjectGraph) -> tuple[ArtifactRoot, ...]:
    values: dict[Path, tuple[str, set[str]]] = {}
    for component in graph.components:
        key = component.key(graph.root)
        candidates: list[tuple[Path, str]] = []
        if component.ecosystem == "node":
            candidates.append((component.path / "node_modules", "node_modules"))
        elif component.ecosystem == "python":
            candidates.extend((
                (component.path / ".venv", "python-environment"),
                (component.path / "__pypackages__", "python-environment"),
            ))
        elif component.ecosystem == "rust":
            candidates.append((component.path / "target", "cargo-target"))
        elif component.ecosystem == "go":
            candidates.append((component.path / "vendor", "go-vendor"))

        for path, category in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not resolved.is_dir() or resolved.is_symlink():
                continue
            existing = values.get(resolved)
            if existing is None:
                values[resolved] = (category, {key})
            else:
                existing[1].add(key)

    return tuple(
        ArtifactRoot(path, category, tuple(sorted(components)))
        for path, (category, components) in sorted(values.items(), key=lambda item: str(item[0]))
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def analyze_physical_duplicates(
    graph: ProjectGraph,
    *,
    min_size_bytes: int = 4096,
) -> PhysicalDuplicateReport:
    if min_size_bytes < 0:
        raise ValueError("min_size_bytes must be non-negative.")
    roots = known_artifact_roots(graph)
    inode_records: dict[tuple[int, int], _InodeRecord] = {}
    files_considered = 0
    skipped: list[str] = []

    for artifact in roots:
        for current, directories, files in os.walk(artifact.path, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name
                for name in directories
                if not (current_path / name).is_symlink()
            )
            for name in sorted(files):
                path = current_path / name
                try:
                    stat = path.stat(follow_symlinks=False)
                except OSError as exc:
                    skipped.append(f"{_relative(graph.root, path)}: {exc}")
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                if stat.st_size < min_size_bytes or stat.st_size == 0:
                    continue
                files_considered += 1
                inode = (stat.st_dev, stat.st_ino)
                relative = _relative(graph.root, path)
                record = inode_records.get(inode)
                if record is None:
                    inode_records[inode] = _InodeRecord(
                        size=stat.st_size,
                        paths={relative},
                        categories={artifact.category},
                        components=set(artifact.components),
                        source_path=path,
                    )
                else:
                    record.paths.add(relative)
                    record.categories.add(artifact.category)
                    record.components.update(artifact.components)

    hardlinks: list[HardlinkObservation] = []
    for record in inode_records.values():
        if len(record.paths) > 1:
            hardlinks.append(HardlinkObservation(
                size=record.size,
                paths=tuple(sorted(record.paths)),
                categories=tuple(sorted(record.categories)),
                components=tuple(sorted(record.components)),
            ))

    by_size: dict[int, list[_InodeRecord]] = defaultdict(list)
    for record in inode_records.values():
        by_size[record.size].append(record)

    by_hash: dict[tuple[int, str], list[_InodeRecord]] = defaultdict(list)
    bytes_hashed = 0
    for size, records in sorted(by_size.items()):
        if len(records) < 2:
            continue
        for record in records:
            try:
                digest = _sha256(record.source_path)
            except OSError as exc:
                skipped.append(f"{_relative(graph.root, record.source_path)}: {exc}")
                continue
            bytes_hashed += size
            by_hash[(size, digest)].append(record)

    groups: list[PhysicalDuplicateGroup] = []
    for (size, digest), records in sorted(by_hash.items(), key=lambda item: (item[0][0], item[0][1])):
        if len(records) < 2:
            continue
        instances = tuple(sorted((
            PhysicalInstance(
                size=record.size,
                paths=tuple(sorted(record.paths)),
                categories=tuple(sorted(record.categories)),
                components=tuple(sorted(record.components)),
            )
            for record in records
        ), key=lambda item: item.paths))
        groups.append(PhysicalDuplicateGroup(
            sha256=digest,
            size=size,
            physical_instances=instances,
            duplicate_content_bytes=size * (len(instances) - 1),
            reclaimable=False,
        ))

    hardlinks.sort(key=lambda item: (item.size, item.paths))
    artifact_rows = tuple({
        "path": _relative(graph.root, artifact.path),
        "category": artifact.category,
        "components": list(artifact.components),
    } for artifact in roots)
    return PhysicalDuplicateReport(
        tuple(groups),
        tuple(hardlinks),
        artifact_rows,
        files_considered,
        len(inode_records),
        bytes_hashed,
        min_size_bytes,
        tuple(sorted(skipped)),
    )
