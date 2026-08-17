from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .workspace_path_safety import WorkspacePathSafetyError, safe_workspace_candidate, validate_workspace_pattern


class UvWorkspaceError(ValueError):
    """Raised when uv workspace membership is invalid or ambiguous."""


@dataclass(frozen=True)
class UvWorkspaceMembership:
    root_component: str
    root: Path
    members: tuple[str, ...]
    member_paths: tuple[Path, ...]
    patterns: tuple[str, ...]
    exclude: tuple[str, ...]
    unmatched_patterns: tuple[str, ...]

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        return {
            "root_component": self.root_component,
            "root": self.root.relative_to(project_root).as_posix() or ".",
            "members": list(self.members),
            "patterns": list(self.patterns),
            "exclude": list(self.exclude),
            "unmatched_patterns": list(self.unmatched_patterns),
        }


def _load(component: Component) -> dict[str, Any]:
    target = component.path / "pyproject.toml"
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UvWorkspaceError(f"Could not read uv workspace manifest {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise UvWorkspaceError(f"pyproject root is not a table: {target}")
    return data


def _workspace_table(data: dict[str, Any]) -> dict[str, Any] | None:
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, dict):
        return None
    workspace = uv.get("workspace")
    return workspace if isinstance(workspace, dict) else None


def _patterns(table: dict[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise UvWorkspaceError(f"tool.uv.workspace.{key} must be an array of non-empty strings.")
    try:
        return tuple(validate_workspace_pattern(item) for item in value)
    except WorkspacePathSafetyError as exc:
        raise UvWorkspaceError(f"Unsafe uv workspace {key} pattern: {exc}") from exc


def _expand(root: Path, pattern: str, candidates: set[Path]) -> set[Path]:
    result: set[Path] = set()
    try:
        matches = root.glob(pattern)
        for match in matches:
            directory = match.parent if match.name == "pyproject.toml" else match
            directory = safe_workspace_candidate(root, directory)
            if directory in candidates and (directory / "pyproject.toml").is_file():
                result.add(directory)
    except WorkspacePathSafetyError as exc:
        raise UvWorkspaceError(f"Unsafe uv workspace pattern {pattern!r}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise UvWorkspaceError(f"Could not expand uv workspace pattern {pattern!r} safely: {exc}") from exc
    return result


def inspect_uv_workspace(graph: ProjectGraph, root_component: Component) -> UvWorkspaceMembership | None:
    if root_component.ecosystem != "python":
        return None
    data = _load(root_component)
    table = _workspace_table(data)
    if table is None:
        return None

    root = root_component.path.resolve()
    python_components = [component for component in graph.components if component.ecosystem == "python"]
    by_path = {component.path.resolve(): component for component in python_components}
    candidates = set(by_path)
    patterns = _patterns(table, "members")
    excludes = _patterns(table, "exclude")

    excluded: set[Path] = set()
    for pattern in excludes:
        excluded.update(_expand(root, pattern, candidates))

    members: set[Path] = {root}
    unmatched: list[str] = []
    for pattern in patterns:
        found = _expand(root, pattern, candidates)
        if not found:
            unmatched.append(pattern)
        members.update(found)
    members.difference_update(excluded - {root})

    for member_path in sorted(members, key=str):
        if member_path == root:
            continue
        component = by_path.get(member_path)
        if component is None:
            continue
        nested = _workspace_table(_load(component))
        if nested is not None:
            raise UvWorkspaceError(
                f"Nested uv workspace root {member_path} is included by workspace {root}; "
                "UPM will not guess nested workspace ownership."
            )

    components = [by_path[path] for path in sorted(members, key=str) if path in by_path]
    return UvWorkspaceMembership(
        root_component=root_component.key(graph.root),
        root=root,
        members=tuple(component.key(graph.root) for component in components),
        member_paths=tuple(component.path.resolve() for component in components),
        patterns=patterns,
        exclude=excludes,
        unmatched_patterns=tuple(unmatched),
    )


def uv_workspace_ownership(graph: ProjectGraph) -> tuple[dict[Path, UvWorkspaceMembership], dict[Path, UvWorkspaceMembership]]:
    roots: dict[Path, UvWorkspaceMembership] = {}
    owners: dict[Path, UvWorkspaceMembership] = {}
    for component in graph.components:
        if component.ecosystem != "python" or "pyproject.toml" not in component.manifests:
            continue
        try:
            workspace = inspect_uv_workspace(graph, component)
        except UvWorkspaceError:
            raise
        if workspace is None:
            continue
        if not (workspace.root / "uv.lock").is_file():
            raise UvWorkspaceError(
                f"uv workspace root {workspace.root} has no authoritative uv.lock."
            )
        roots[workspace.root] = workspace
        for member_path in workspace.member_paths:
            if member_path == workspace.root:
                continue
            existing = owners.get(member_path)
            if existing is not None and existing.root != workspace.root:
                raise UvWorkspaceError(
                    f"Python component {member_path} is claimed by multiple uv workspaces: "
                    f"{existing.root} and {workspace.root}."
                )
            owners[member_path] = workspace
    return roots, owners
