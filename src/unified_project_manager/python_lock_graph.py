from __future__ import annotations

import re
import tomllib
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class PythonLockGraphError(ValueError):
    """Raised when a structured Python lock graph cannot be represented safely."""


@dataclass(frozen=True)
class PythonLockGraphPlan:
    component: str
    manager: str
    lockfile: Path

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "python",
            "manager": self.manager,
            "lockfile": self.lockfile.relative_to(root).as_posix(),
            "source": f"structured {self.lockfile.name} relationship records",
            "execution": False,
            "network": False,
            "mutation": False,
        }


@dataclass(frozen=True)
class PythonLockedPackage:
    component: str
    package_id: str
    name: str
    version: str
    source_kind: str
    groups: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PythonLockEdge:
    component: str
    source_id: str
    dependency_name: str
    target_id: str | None
    candidate_ids: tuple[str, ...]
    requirement: str | None = None
    marker: str | None = None
    optional: bool = False
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PythonLockGraphResult:
    plan: PythonLockGraphPlan
    packages: list[PythonLockedPackage]
    edges: list[PythonLockEdge]
    project_roots: tuple[str, ...]
    succeeded: bool = True
    error: str = ""

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "error": self.error,
            "project_roots": list(self.project_roots),
            "packages": [package.to_dict() for package in self.packages],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class PythonLockImpact:
    component: str
    package_id: str
    name: str
    version: str
    manager: str
    project_paths: tuple[tuple[str, ...], ...]
    ambiguous_references: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_id(name: str, version: str, ordinal: int, source_kind: str) -> str:
    return f"{normalize_python_name(name)}@{version}#{source_kind}#{ordinal}"


def _source_kind(record: dict[str, Any]) -> str:
    source = record.get("source")
    if isinstance(source, dict):
        source_type = source.get("type")
        if isinstance(source_type, str) and source_type:
            if source_type in {"git", "directory", "file", "url"}:
                return source_type
            return "registry"
    for key in ("git", "path", "url"):
        if key in record:
            return key
    if record.get("editable") is True:
        return "editable"
    return "registry"


def _requirement_name(value: str) -> tuple[str | None, str | None, str | None]:
    """Extract PEP-508-ish name, requirement text, and marker without resolving it."""
    before_marker, separator, marker = value.partition(";")
    marker_value = marker.strip() if separator else None
    token = before_marker.strip()
    if not token:
        return None, None, marker_value
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", token)
    if not match:
        return None, token or None, marker_value
    name = match.group(1)
    remainder = token[match.end():].strip()
    if remainder.startswith("["):
        close = remainder.find("]")
        if close >= 0:
            remainder = remainder[close + 1:].strip()
    return name, remainder or None, marker_value


def _poetry_dependency_records(name: str, value: object) -> list[tuple[str, str | None, str | None, bool]]:
    records: list[tuple[str, str | None, str | None, bool]] = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, str):
            records.append((name, item or None, None, False))
            continue
        if not isinstance(item, dict):
            continue
        requirement = item.get("version") if isinstance(item.get("version"), str) else None
        marker = item.get("markers") if isinstance(item.get("markers"), str) else None
        python = item.get("python") if isinstance(item.get("python"), str) else None
        platform = item.get("platform") if isinstance(item.get("platform"), str) else None
        marker_parts = [value for value in (marker, python, platform) if value]
        records.append((name, requirement, " && ".join(marker_parts) or None, bool(item.get("optional"))))
    return records


def _package_dependency_records(manager: str, record: dict[str, Any]) -> list[tuple[str, str | None, str | None, bool]]:
    if manager == "poetry":
        dependencies = record.get("dependencies")
        if not isinstance(dependencies, dict):
            return []
        result: list[tuple[str, str | None, str | None, bool]] = []
        for name, value in dependencies.items():
            if isinstance(name, str):
                result.extend(_poetry_dependency_records(name, value))
        return result

    dependencies = record.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    result = []
    for value in dependencies:
        if not isinstance(value, str):
            continue
        name, requirement, marker = _requirement_name(value)
        if name:
            result.append((name, requirement, marker, False))
    return result


def _load_lock(plan: PythonLockGraphPlan) -> dict[str, Any]:
    try:
        with plan.lockfile.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PythonLockGraphError(f"Could not read {plan.lockfile}: {exc}") from exc
    if not isinstance(data, dict):
        raise PythonLockGraphError(f"{plan.lockfile} root is not a TOML table.")
    return data


def _component_for_plan(graph: ProjectGraph, plan: PythonLockGraphPlan) -> Component:
    return next(
        component for component in graph.components
        if component.key(graph.root) == plan.component
    )


def _scope_is_optional(scope: str) -> bool:
    return scope == "optional" or scope.startswith("optional:")


def plan_python_lock_graphs(graph: ProjectGraph, selector: str | None = None) -> list[PythonLockGraphPlan]:
    candidates: list[tuple[Component, Path]] = []
    for component in graph.components:
        if component.ecosystem != "python" or component.manager not in {"poetry", "pdm"}:
            continue
        name = "poetry.lock" if component.manager == "poetry" else "pdm.lock"
        if name not in component.lockfiles:
            continue
        candidates.append((component, component.path / name))

    if selector is not None:
        matches = [
            item for item in candidates
            if selector in {
                item[0].key(graph.root),
                item[0].relative_path(graph.root),
                item[0].ecosystem,
                item[0].metadata.get("name"),
            }
        ]
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component, _ in matches)
            raise PythonLockGraphError(
                f"Component selector {selector!r} is ambiguous for structured Python lock graph: {choices}"
            )
        candidates = matches

    return [
        PythonLockGraphPlan(component.key(graph.root), component.manager or "", lockfile)
        for component, lockfile in sorted(candidates, key=lambda item: str(item[1]))
    ]


def execute_python_lock_graph(graph: ProjectGraph, plan: PythonLockGraphPlan) -> PythonLockGraphResult:
    try:
        data = _load_lock(plan)
        component = _component_for_plan(graph, plan)
    except (PythonLockGraphError, StopIteration) as exc:
        return PythonLockGraphResult(plan, [], [], (), False, str(exc))

    records = data.get("package")
    if not isinstance(records, list):
        return PythonLockGraphResult(
            plan, [], [], (), False,
            f"{plan.lockfile.name} has no structured package array.",
        )

    packages: list[PythonLockedPackage] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    for ordinal, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        name = record.get("name")
        version = record.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        source_kind = _source_kind(record)
        package_id = _package_id(name, version, ordinal, source_kind)
        groups_value = record.get("groups")
        groups = tuple(sorted(value for value in groups_value if isinstance(value, str))) if isinstance(groups_value, list) else ()
        packages.append(PythonLockedPackage(
            plan.component, package_id, name, version, source_kind, groups,
        ))
        raw_by_id[package_id] = record
        by_name[normalize_python_name(name)].append(package_id)

    package_by_id = {package.package_id: package for package in packages}
    edges: list[PythonLockEdge] = []

    def add_reference(source_id: str, name: str, requirement: str | None, marker: str | None, optional: bool) -> None:
        candidates = tuple(sorted(by_name.get(normalize_python_name(name), [])))
        target = candidates[0] if len(candidates) == 1 else None
        edges.append(PythonLockEdge(
            component=plan.component,
            source_id=source_id,
            dependency_name=name,
            target_id=target,
            candidate_ids=candidates,
            requirement=requirement,
            marker=marker,
            optional=optional,
            ambiguous=len(candidates) > 1,
        ))

    for package_id, record in raw_by_id.items():
        for name, requirement, marker, optional in _package_dependency_records(plan.manager, record):
            add_reference(package_id, name, requirement, marker, optional)

    project_root = f"project:{plan.component}"
    for dependency in component.dependencies:
        add_reference(
            project_root,
            dependency.name,
            dependency.requirement,
            None,
            _scope_is_optional(dependency.scope),
        )

    packages.sort(key=lambda item: (normalize_python_name(item.name), item.version, item.package_id))
    edges.sort(key=lambda item: (
        item.source_id, normalize_python_name(item.dependency_name), item.target_id or "", item.requirement or "", item.marker or "",
    ))
    return PythonLockGraphResult(plan, packages, edges, (project_root,))


def analyze_python_lock_impact(result: PythonLockGraphResult, package_name: str) -> list[PythonLockImpact]:
    if not result.succeeded:
        raise PythonLockGraphError(result.error)
    packages = {package.package_id: package for package in result.packages}
    forward: dict[str, set[str]] = defaultdict(set)
    ambiguous_by_name: dict[str, int] = defaultdict(int)
    for edge in result.edges:
        if edge.target_id:
            forward[edge.source_id].add(edge.target_id)
        elif edge.ambiguous:
            for candidate in edge.candidate_ids:
                package = packages.get(candidate)
                if package is not None:
                    ambiguous_by_name[normalize_python_name(package.name)] += 1

    target_name = normalize_python_name(package_name)
    impacts: list[PythonLockImpact] = []
    for target in result.packages:
        if normalize_python_name(target.name) != target_name:
            continue
        paths: list[tuple[str, ...]] = []
        for root in result.project_roots:
            queue: deque[tuple[str, tuple[str, ...]]] = deque([(root, (root,))])
            visited: set[str] = set()
            while queue:
                current, path = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                if current == target.package_id:
                    labels = tuple(
                        (packages[value].name + "@" + packages[value].version) if value in packages else plan_label
                        for value, plan_label in ((entry, entry) for entry in path)
                    )
                    paths.append(labels)
                    break
                for child in sorted(forward.get(current, set())):
                    if child not in path:
                        queue.append((child, (*path, child)))
        if not paths:
            continue
        impacts.append(PythonLockImpact(
            component=result.plan.component,
            package_id=target.package_id,
            name=target.name,
            version=target.version,
            manager=result.plan.manager,
            project_paths=tuple(sorted(set(paths))),
            ambiguous_references=ambiguous_by_name[target_name],
        ))
    return impacts
