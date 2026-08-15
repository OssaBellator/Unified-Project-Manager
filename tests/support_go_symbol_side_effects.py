from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class SideEffectSnapshotError(ValueError):
    """Raised when a validation tree cannot be snapshotted safely."""


@dataclass(frozen=True)
class FileState:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class FileTreeSnapshot:
    root: str
    files: tuple[FileState, ...]

    def by_path(self) -> dict[str, FileState]:
        return {entry.path: entry for entry in self.files}

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [entry.to_dict() for entry in self.files],
        }


@dataclass(frozen=True)
class ModifiedFileState:
    path: str
    before: FileState
    after: FileState

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


@dataclass(frozen=True)
class FileTreeDelta:
    root: str
    added: tuple[FileState, ...]
    removed: tuple[FileState, ...]
    modified: tuple[ModifiedFileState, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "changed": self.changed,
            "added": [entry.to_dict() for entry in self.added],
            "removed": [entry.to_dict() for entry in self.removed],
            "modified": [entry.to_dict() for entry in self.modified],
        }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(root: str | Path) -> FileTreeSnapshot:
    target = Path(root).expanduser().resolve()
    if not target.is_dir():
        raise SideEffectSnapshotError(f"snapshot root is not a directory: {target}")

    entries: list[FileState] = []
    for current, dirnames, filenames in os.walk(target, followlinks=False):
        current_path = Path(current)
        for dirname in list(dirnames):
            candidate = current_path / dirname
            if candidate.is_symlink():
                raise SideEffectSnapshotError(
                    f"snapshot root contains a symlinked directory: {candidate}"
                )
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink():
                raise SideEffectSnapshotError(
                    f"snapshot root contains a symlinked file: {candidate}"
                )
            if not candidate.is_file():
                raise SideEffectSnapshotError(
                    f"snapshot root contains a non-regular file: {candidate}"
                )
            relative = candidate.relative_to(target).as_posix()
            entries.append(
                FileState(
                    path=relative,
                    size=candidate.stat().st_size,
                    sha256=_hash_file(candidate),
                )
            )

    return FileTreeSnapshot(
        root=str(target),
        files=tuple(sorted(entries, key=lambda entry: entry.path)),
    )


def diff_snapshots(before: FileTreeSnapshot, after: FileTreeSnapshot) -> FileTreeDelta:
    if before.root != after.root:
        raise SideEffectSnapshotError(
            "cannot compare snapshots from different roots: "
            f"{before.root!r} != {after.root!r}"
        )

    before_by_path = before.by_path()
    after_by_path = after.by_path()
    added = tuple(
        after_by_path[path]
        for path in sorted(after_by_path.keys() - before_by_path.keys())
    )
    removed = tuple(
        before_by_path[path]
        for path in sorted(before_by_path.keys() - after_by_path.keys())
    )
    modified = tuple(
        ModifiedFileState(path, before_by_path[path], after_by_path[path])
        for path in sorted(before_by_path.keys() & after_by_path.keys())
        if before_by_path[path] != after_by_path[path]
    )
    return FileTreeDelta(before.root, added, removed, modified)


def snapshot_named_roots(roots: Mapping[str, str | Path]) -> dict[str, FileTreeSnapshot]:
    return {
        name: snapshot_tree(root)
        for name, root in sorted(roots.items())
    }


def diff_named_roots(
    before: Mapping[str, FileTreeSnapshot],
    after: Mapping[str, FileTreeSnapshot],
) -> dict[str, FileTreeDelta]:
    if set(before) != set(after):
        raise SideEffectSnapshotError(
            "cannot compare named snapshots with different labels: "
            f"before={sorted(before)}, after={sorted(after)}"
        )
    return {
        name: diff_snapshots(before[name], after[name])
        for name in sorted(before)
    }
