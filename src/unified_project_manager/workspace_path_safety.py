from __future__ import annotations

import os
import stat
from pathlib import Path


class WorkspacePathSafetyError(ValueError):
    """Raised before workspace declarations can inspect paths outside their root."""


def validate_workspace_pattern(pattern: str) -> str:
    """Validate one project-owned workspace glob using portable POSIX path syntax."""

    if not isinstance(pattern, str) or not pattern or any(char in pattern for char in ("\x00", "\r", "\n")):
        raise WorkspacePathSafetyError("workspace patterns must be non-empty bounded text")
    if len(pattern) > 1024:
        raise WorkspacePathSafetyError("workspace pattern exceeds 1024 characters")
    if "\\" in pattern:
        raise WorkspacePathSafetyError("workspace patterns must use project-relative POSIX '/' separators")
    if pattern.startswith(("/", "~")) or ":" in pattern:
        raise WorkspacePathSafetyError("workspace patterns must be project-relative and may not name an absolute/source path")
    segments = pattern.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise WorkspacePathSafetyError("workspace patterns may not contain empty, dot, or parent path segments")
    return pattern


def _is_reparse_or_symlink(path: Path) -> bool:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse and attributes & reparse)


def safe_workspace_candidate(root: Path, candidate: Path) -> Path:
    """Return a canonical in-root candidate, refusing symlink/reparse traversal first."""

    root = root.resolve()
    absolute = candidate.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathSafetyError("workspace pattern resolved outside the project root") from exc

    current = root
    for segment in relative.parts:
        current = current / segment
        try:
            if _is_reparse_or_symlink(current):
                raise WorkspacePathSafetyError("workspace pattern traverses a symlink or reparse point")
        except FileNotFoundError:
            break
        except OSError as exc:
            raise WorkspacePathSafetyError("workspace candidate identity could not be verified safely") from exc

    try:
        resolved = absolute.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspacePathSafetyError("workspace candidate resolves outside the project root") from exc
    return resolved
