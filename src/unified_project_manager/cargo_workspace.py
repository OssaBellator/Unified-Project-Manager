from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .workspace_path_safety import WorkspacePathSafetyError, safe_workspace_candidate, validate_workspace_pattern


class CargoWorkspaceError(ValueError):
    """Raised when static Cargo workspace ownership is contradictory or invalid."""


@dataclass(frozen=True)
class CargoWorkspaceMembership:
    root_component: str
    root: Path
    members: tuple[str, ...]
    member_paths: tuple[Path, ...]
    explicit_members: tuple[str, ...]
    exclude: tuple[str, ...]
    unmatched_member_patterns: tuple[str, ...]

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        return {
            "root_component": self.root_component,
            "root": self.root.relative_to(project_root).as_posix() or ".",
            "members": list(self.members),
            "explicit_members": list(self.explicit_members),
            "exclude": list(self.exclude),
            "unmatched_member_patterns": list(self.unmatched_member_patterns),
        }


def _load_manifest(component: Component) -> dict[str, Any]:
    target = component.path / "Cargo.toml"
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CargoWorkspaceError(f"Could not read Cargo manifest {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise CargoWorkspaceError(f"Cargo manifest root is not a table: {target}")
    return data


def _patterns(table: dict[str, Any], field: str) -> tuple[str, ...]:
    values = table.get(field)
    if not isinstance(values, list):
        return ()
    patterns = tuple(value for value in values if isinstance(value, str) and value)
    try:
        return tuple(validate_workspace_pattern(pattern) for pattern in patterns)
    except WorkspacePathSafetyError as exc:
        raise CargoWorkspaceError(f"Unsafe Cargo workspace {field} pattern: {exc}") from exc


def _expand_pattern(root: Path, pattern: str, candidates: set[Path]) -> set[Path]:
    result: set[Path] = set()
    try:
        matches = root.glob(pattern)
        for match in matches:
            directory = match.parent if match.name == "Cargo.toml" else match
            directory = safe_workspace_candidate(root, directory)
            if directory in candidates and (directory / "Cargo.toml").is_file():
                result.add(directory)
    except WorkspacePathSafetyError as exc:
        raise CargoWorkspaceError(f"Unsafe Cargo workspace pattern {pattern!r}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise CargoWorkspaceError(f"Could not expand Cargo workspace pattern {pattern!r} safely: {exc}") from exc
    return result


def _dependency_tables(data: dict[str, Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for name in ("dependencies", "dev-dependencies", "build-dependencies"):
        value = data.get(name)
        if isinstance(value, dict):
            tables.append(value)
    target = data.get("target")
    if isinstance(target, dict):
        for target_table in target.values():
            if not isinstance(target_table, dict):
                continue
            for name in ("dependencies", "dev-dependencies", "build-dependencies"):
                value = target_table.get(name)
                if isinstance(value, dict):
                    tables.append(value)
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        dependencies = workspace.get("dependencies")
        if isinstance(dependencies, dict):
            tables.append(dependencies)
    return tables


def _path_dependencies(component: Component, data: dict[str, Any]) -> set[Path]:
    paths: set[Path] = set()
    for table in _dependency_tables(data):
        for value in table.values():
            if not isinstance(value, dict):
                continue
            raw = value.get("path")
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = component.path / path
            paths.add(path.resolve())
    return paths


def _explicit_workspace_root(component: Component, data: dict[str, Any]) -> Path | None:
    package = data.get("package")
    if not isinstance(package, dict):
        return None
    raw = package.get("workspace")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = component.path / path
    return path.resolve()


def inspect_cargo_workspace(graph: ProjectGraph, root_component: Component) -> CargoWorkspaceMembership | None:
    if root_component.ecosystem != "rust":
        return None
    root_data = _load_manifest(root_component)
    workspace = root_data.get("workspace")
    if not isinstance(workspace, dict):
        return None

    rust_components = [component for component in graph.components if component.ecosystem == "rust"]
    by_path = {component.path.resolve(): component for component in rust_components}
    candidate_paths = set(by_path)
    root_path = root_component.path.resolve()
    explicit_patterns = _patterns(workspace, "members")
    exclude_patterns = _patterns(workspace, "exclude")

    excluded: set[Path] = set()
    for pattern in exclude_patterns:
        excluded.update(_expand_pattern(root_path, pattern, candidate_paths))

    members: set[Path] = set()
    package = root_data.get("package")
    if isinstance(package, dict):
        members.add(root_path)

    unmatched: list[str] = []
    for pattern in explicit_patterns:
        found = _expand_pattern(root_path, pattern, candidate_paths)
        if not found:
            unmatched.append(pattern)
        members.update(found)

    manifests: dict[Path, dict[str, Any]] = {root_path: root_data}
    for component in rust_components:
        path = component.path.resolve()
        if path == root_path:
            continue
        data = _load_manifest(component)
        manifests[path] = data
        explicit_root = _explicit_workspace_root(component, data)
        if explicit_root == root_path:
            members.add(path)

    members.difference_update(excluded - {root_path})

    # Cargo automatically treats path dependencies inside a workspace directory
    # as members. Follow those references transitively across discovered manifests.
    queue = list(sorted(members, key=str))
    visited: set[Path] = set()
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        component = by_path.get(current)
        data = manifests.get(current)
        if component is None or data is None:
            continue
        for dependency_path in sorted(_path_dependencies(component, data), key=str):
            if dependency_path not in candidate_paths or dependency_path in excluded:
                continue
            try:
                dependency_path.relative_to(root_path)
            except ValueError:
                continue
            if dependency_path not in members:
                members.add(dependency_path)
                queue.append(dependency_path)

    member_components = [by_path[path] for path in sorted(members, key=str) if path in by_path]
    return CargoWorkspaceMembership(
        root_component=root_component.key(graph.root),
        root=root_path,
        members=tuple(component.key(graph.root) for component in member_components),
        member_paths=tuple(component.path.resolve() for component in member_components),
        explicit_members=explicit_patterns,
        exclude=exclude_patterns,
        unmatched_member_patterns=tuple(unmatched),
    )


def cargo_workspace_ownership(graph: ProjectGraph) -> tuple[dict[Path, CargoWorkspaceMembership], dict[Path, CargoWorkspaceMembership]]:
    roots: dict[Path, CargoWorkspaceMembership] = {}
    owners: dict[Path, CargoWorkspaceMembership] = {}
    for component in graph.components:
        if component.ecosystem != "rust" or not component.metadata.get("workspace"):
            continue
        model = inspect_cargo_workspace(graph, component)
        if model is None:
            continue
        roots[model.root] = model
        for member_path in model.member_paths:
            if member_path == model.root:
                continue
            existing = owners.get(member_path)
            if existing is not None and existing.root != model.root:
                raise CargoWorkspaceError(
                    f"Cargo component {member_path} is claimed by multiple workspace roots: "
                    f"{existing.root} and {model.root}."
                )
            owners[member_path] = model
    return roots, owners
