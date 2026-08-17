from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .workspace_path_safety import WorkspacePathSafetyError, safe_workspace_candidate, validate_workspace_pattern


class NodeWorkspaceError(ValueError):
    """Raised when a package.json workspace declaration is invalid."""


@dataclass(frozen=True)
class NodeWorkspaceMember:
    path: Path
    name: str | None
    version: str | None
    private: bool | None
    package_manager: str | None

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "path": self.path.relative_to(root).as_posix(),
            "name": self.name,
            "version": self.version,
            "private": self.private,
            "package_manager": self.package_manager,
        }


@dataclass(frozen=True)
class NodeWorkspaceIssue:
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeWorkspace:
    root: Path
    manager: str | None
    patterns: tuple[str, ...]
    members: tuple[NodeWorkspaceMember, ...]
    issues: tuple[NodeWorkspaceIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "manager": self.manager,
            "patterns": list(self.patterns),
            "members": [member.to_dict(self.root) for member in self.members],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _manager(data: dict[str, Any]) -> str | None:
    value = data.get("packageManager")
    if isinstance(value, str) and value:
        return value.split("@", 1)[0]
    dev_engines = data.get("devEngines")
    if isinstance(dev_engines, dict):
        package_manager = dev_engines.get("packageManager")
        if isinstance(package_manager, dict) and isinstance(package_manager.get("name"), str):
            return package_manager["name"]
    return None


def _workspace_patterns(data: dict[str, Any]) -> tuple[str, ...]:
    value = data.get("workspaces")
    if value is None:
        return ()
    if isinstance(value, list):
        patterns = value
    elif isinstance(value, dict) and isinstance(value.get("packages"), list):
        patterns = value["packages"]
    else:
        raise NodeWorkspaceError("package.json workspaces must be an array or an object with a packages array.")
    if not all(isinstance(item, str) and item.strip() for item in patterns):
        raise NodeWorkspaceError("package.json workspace patterns must be non-empty strings.")
    normalized = tuple(dict.fromkeys(item.strip() for item in patterns))
    try:
        return tuple(validate_workspace_pattern(pattern) for pattern in normalized)
    except WorkspacePathSafetyError as exc:
        raise NodeWorkspaceError(f"Unsafe package.json workspace pattern: {exc}") from exc


def _member(directory: Path) -> NodeWorkspaceMember:
    package_json = directory / "package.json"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NodeWorkspaceError(f"Could not read workspace member {package_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise NodeWorkspaceError(f"Workspace member {package_json} is not a JSON object.")
    private = data.get("private") if isinstance(data.get("private"), bool) else None
    return NodeWorkspaceMember(
        path=directory,
        name=data.get("name") if isinstance(data.get("name"), str) else None,
        version=data.get("version") if isinstance(data.get("version"), str) else None,
        private=private,
        package_manager=_manager(data),
    )


def inspect_node_workspace(root: str | Path) -> NodeWorkspace | None:
    root_path = Path(root).expanduser().resolve()
    package_json = root_path / "package.json"
    if not package_json.is_file():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NodeWorkspaceError(f"Could not read {package_json}: {exc}") from exc
    if not isinstance(data, dict):
        raise NodeWorkspaceError(f"{package_json} is not a JSON object.")
    patterns = _workspace_patterns(data)
    if not patterns:
        return None

    issues: list[NodeWorkspaceIssue] = []
    member_paths: set[Path] = set()
    for pattern in patterns:
        matched = False
        for candidate in root_path.glob(pattern):
            try:
                candidate = safe_workspace_candidate(root_path, candidate)
            except WorkspacePathSafetyError as exc:
                raise NodeWorkspaceError(f"Unsafe package.json workspace match for {pattern!r}: {exc}") from exc
            if not candidate.is_dir():
                continue
            if candidate == root_path or "node_modules" in candidate.parts:
                continue
            if (candidate / "package.json").is_file():
                member_paths.add(candidate)
                matched = True
        if not matched:
            issues.append(NodeWorkspaceIssue(
                "workspace.pattern-unmatched",
                f"Workspace pattern {pattern!r} did not match a package.json directory.",
            ))

    members: list[NodeWorkspaceMember] = []
    manager = _manager(data)
    names: dict[str, list[Path]] = {}
    for path in sorted(member_paths, key=lambda value: value.relative_to(root_path).as_posix()):
        member = _member(path)
        members.append(member)
        if member.name:
            names.setdefault(member.name, []).append(path)
        if member.package_manager and manager and member.package_manager != manager:
            issues.append(NodeWorkspaceIssue(
                "workspace.manager-mismatch",
                f"Workspace root uses {manager}, but member declares {member.package_manager}.",
                path.relative_to(root_path).as_posix(),
            ))

    for name, paths in sorted(names.items()):
        if len(paths) > 1:
            issues.append(NodeWorkspaceIssue(
                "workspace.duplicate-package-name",
                f"Workspace package name {name!r} is declared by multiple members.",
            ))

    # Detect nested packages that look project-like but are outside the declared workspace.
    for package in root_path.rglob("package.json"):
        try:
            directory = safe_workspace_candidate(root_path, package.parent)
        except WorkspacePathSafetyError as exc:
            raise NodeWorkspaceError(f"Unsafe nested package.json path: {exc}") from exc
        if directory == root_path or directory in member_paths:
            continue
        relative = directory.relative_to(root_path)
        if any(part in {"node_modules", ".git", "dist", "build"} for part in relative.parts):
            continue
        issues.append(NodeWorkspaceIssue(
            "workspace.unlisted-package",
            "Nested package.json is not covered by the workspace declaration.",
            relative.as_posix(),
        ))

    return NodeWorkspace(root_path, manager, patterns, tuple(members), tuple(issues))
