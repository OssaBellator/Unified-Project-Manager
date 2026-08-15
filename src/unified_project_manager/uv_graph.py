from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .uv_workspace import UvWorkspaceError, uv_workspace_ownership


class UvGraphError(ValueError):
    """Raised when uv.lock relationship state cannot be interpreted safely."""


@dataclass(frozen=True)
class UvGraphPlan:
    component: str
    lockfile: Path
    selected_component: str | None = None
    selected_project_name: str | None = None
    selected_project_version: str | None = None

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "python",
            "manager": "uv",
            "source": "uv.lock",
            "lockfile": self.lockfile.relative_to(root).as_posix(),
            "network": False,
            "execution": False,
            "selected_component": self.selected_component,
            "selected_project_name": self.selected_project_name,
            "selected_project_version": self.selected_project_version,
        }


@dataclass(frozen=True)
class UvLockedPackage:
    component: str
    package_id: str
    name: str
    version: str
    source: str | None
    source_kind: str | None
    project_member: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UvDependencyEdge:
    component: str
    source_id: str
    dependency_name: str
    requested_version: str | None
    marker: str | None
    target_id: str | None
    candidate_ids: tuple[str, ...]
    ambiguous: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UvGraphResult:
    plan: UvGraphPlan
    packages: list[UvLockedPackage]
    edges: list[UvDependencyEdge]
    succeeded: bool = True
    error: str = ""

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "packages": [package.to_dict() for package in self.packages],
            "edges": [edge.to_dict() for edge in self.edges],
            "ambiguous_edges": sum(1 for edge in self.edges if edge.ambiguous),
            "error": self.error,
        }


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _selected_plan(owner: Component, selected: Component, graph: ProjectGraph, lockfile: Path) -> UvGraphPlan:
    name = selected.metadata.get("name")
    version = selected.metadata.get("version")
    return UvGraphPlan(
        owner.key(graph.root),
        lockfile,
        selected_component=selected.key(graph.root),
        selected_project_name=name if isinstance(name, str) and name else None,
        selected_project_version=version if isinstance(version, str) and version else None,
    )


def plan_uv_graphs(graph: ProjectGraph, selector: str | None = None) -> list[UvGraphPlan]:
    """Plan one static uv.lock graph per authoritative lock owner.

    uv workspaces share a lockfile. Unscoped planning reads each shared lock once;
    selecting a member promotes the query to the workspace root while retaining
    the selected project identity for downstream why/impact scoping.
    """
    try:
        roots, owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise UvGraphError(str(exc)) from exc

    python_components = [component for component in graph.components if component.ecosystem == "python"]
    by_path = {component.path.resolve(): component for component in python_components}

    if selector is not None:
        matches = [component for component in python_components if _matches(component, graph, selector)]
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise UvGraphError(f"Component selector '{selector}' is ambiguous for uv graph ingestion: {choices}")
        if not matches:
            return []
        selected = matches[0]
        selected_path = selected.path.resolve()
        workspace = owners.get(selected_path)
        if workspace is not None:
            owner = by_path.get(workspace.root)
            if owner is None:
                raise UvGraphError(f"Could not find discovered uv workspace root component at {workspace.root}.")
            return [_selected_plan(owner, selected, graph, workspace.root / "uv.lock")]
        root_workspace = roots.get(selected_path)
        if root_workspace is not None:
            return [_selected_plan(selected, selected, graph, root_workspace.root / "uv.lock")]
        if selected.manager == "uv" and "uv.lock" in selected.lockfiles:
            return [_selected_plan(selected, selected, graph, selected.path / "uv.lock")]
        return []

    plans: list[UvGraphPlan] = []
    for component in python_components:
        path = component.path.resolve()
        if path in owners:
            continue
        workspace = roots.get(path)
        if workspace is not None:
            plans.append(UvGraphPlan(component.key(graph.root), workspace.root / "uv.lock"))
            continue
        if component.manager == "uv" and "uv.lock" in component.lockfiles:
            plans.append(UvGraphPlan(component.key(graph.root), component.path / "uv.lock"))
    plans.sort(key=lambda plan: plan.lockfile.relative_to(graph.root).as_posix())
    return plans


def uv_provider_component_keys(
    graph: ProjectGraph,
    plans: Iterable[UvGraphPlan] | None = None,
) -> set[str]:
    """Return discovered Python components served by the supplied uv plans."""
    selected = tuple(plans) if plans is not None else tuple(plan_uv_graphs(graph))
    if not selected:
        return set()
    try:
        roots, _owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise UvGraphError(str(exc)) from exc

    result: set[str] = set()
    for plan in selected:
        if plan.selected_component is not None:
            result.add(plan.component)
            result.add(plan.selected_component)
            continue
        workspace = roots.get(plan.lockfile.parent.resolve())
        if workspace is not None:
            result.update(workspace.members)
        else:
            result.add(plan.component)
    return result


def _source_text(value: object) -> tuple[str | None, str | None, bool]:
    if not isinstance(value, dict) or not value:
        return None, None, False
    for kind in ("editable", "virtual", "directory", "path", "git", "url", "registry"):
        source = value.get(kind)
        if isinstance(source, str):
            return f"{kind}:{source}", kind, kind in {"editable", "virtual", "directory", "path"}
    return json.dumps(value, sort_keys=True, separators=(",", ":")), "other", False


def _package_id(name: str, version: str, source: str | None) -> str:
    identity = "\0".join((name.lower(), version, source or ""))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"uv:{name}@{version}:{digest}"


def _dependency_marker(value: dict[str, Any]) -> str | None:
    marker = value.get("marker")
    if isinstance(marker, str):
        return marker
    markers = value.get("markers")
    if isinstance(markers, str):
        return markers
    return None


def parse_uv_lock(
    text: str,
    component: str,
    lockfile: Path,
    *,
    selected_component: str | None = None,
    selected_project_name: str | None = None,
    selected_project_version: str | None = None,
) -> UvGraphResult:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UvGraphError(f"Could not parse uv.lock: {exc}") from exc
    raw_packages = data.get("package")
    if not isinstance(raw_packages, list):
        raise UvGraphError("uv.lock has no package array.")

    packages: list[UvLockedPackage] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[UvLockedPackage]] = {}
    for record in raw_packages:
        if not isinstance(record, dict):
            continue
        name = record.get("name")
        version = record.get("version")
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            continue
        source, source_kind, project_member = _source_text(record.get("source"))
        package_id = _package_id(name, version, source)
        package = UvLockedPackage(component, package_id, name, version, source, source_kind, project_member)
        packages.append(package)
        raw_by_id[package_id] = record
        by_name.setdefault(name.lower(), []).append(package)

    edges: list[UvDependencyEdge] = []
    for package in packages:
        record = raw_by_id[package.package_id]
        dependencies = record.get("dependencies")
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if isinstance(dependency, str):
                dependency = {"name": dependency}
            if not isinstance(dependency, dict):
                continue
            name = dependency.get("name")
            if not isinstance(name, str) or not name:
                continue
            requested_version = dependency.get("version") if isinstance(dependency.get("version"), str) else None
            requested_source, _kind, _member = _source_text(dependency.get("source"))
            candidates = list(by_name.get(name.lower(), []))
            if requested_version:
                candidates = [candidate for candidate in candidates if candidate.version == requested_version]
            if requested_source:
                candidates = [candidate for candidate in candidates if candidate.source == requested_source]
            candidate_ids = tuple(sorted(candidate.package_id for candidate in candidates))
            target_id = candidate_ids[0] if len(candidate_ids) == 1 else None
            edges.append(UvDependencyEdge(
                component=component,
                source_id=package.package_id,
                dependency_name=name,
                requested_version=requested_version,
                marker=_dependency_marker(dependency),
                target_id=target_id,
                candidate_ids=candidate_ids,
                ambiguous=len(candidate_ids) != 1,
            ))

    packages.sort(key=lambda item: (not item.project_member, item.name.lower(), item.version, item.package_id))
    edges.sort(key=lambda item: (
        item.source_id, item.dependency_name.lower(), item.requested_version or "", item.marker or "", item.candidate_ids,
    ))
    return UvGraphResult(
        UvGraphPlan(
            component,
            lockfile,
            selected_component=selected_component,
            selected_project_name=selected_project_name,
            selected_project_version=selected_project_version,
        ),
        packages,
        edges,
    )


def execute_uv_graph(plan: UvGraphPlan) -> UvGraphResult:
    try:
        text = plan.lockfile.read_text(encoding="utf-8")
        return parse_uv_lock(
            text,
            plan.component,
            plan.lockfile,
            selected_component=plan.selected_component,
            selected_project_name=plan.selected_project_name,
            selected_project_version=plan.selected_project_version,
        )
    except (OSError, UnicodeDecodeError, UvGraphError) as exc:
        return UvGraphResult(plan, [], [], False, str(exc))
