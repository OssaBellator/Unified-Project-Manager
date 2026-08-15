from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class UvGraphError(ValueError):
    """Raised when uv.lock relationship state cannot be interpreted safely."""


@dataclass(frozen=True)
class UvGraphPlan:
    component: str
    lockfile: Path

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "python",
            "manager": "uv",
            "source": "uv.lock",
            "lockfile": self.lockfile.relative_to(root).as_posix(),
            "network": False,
            "execution": False,
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


def plan_uv_graphs(graph: ProjectGraph, selector: str | None = None) -> list[UvGraphPlan]:
    components = [
        component for component in graph.components
        if component.ecosystem == "python" and component.manager == "uv" and "uv.lock" in component.lockfiles
    ]
    if selector is not None:
        components = [component for component in components if _matches(component, graph, selector)]
        if len(components) > 1:
            choices = ", ".join(component.key(graph.root) for component in components)
            raise UvGraphError(f"Component selector '{selector}' is ambiguous for uv graph ingestion: {choices}")
    return [UvGraphPlan(component.key(graph.root), component.path / "uv.lock") for component in components]


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


def parse_uv_lock(text: str, component: str, lockfile: Path) -> UvGraphResult:
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
    return UvGraphResult(UvGraphPlan(component, lockfile), packages, edges)


def execute_uv_graph(plan: UvGraphPlan) -> UvGraphResult:
    try:
        text = plan.lockfile.read_text(encoding="utf-8")
        return parse_uv_lock(text, plan.component, plan.lockfile)
    except (OSError, UnicodeDecodeError, UvGraphError) as exc:
        return UvGraphResult(plan, [], [], False, str(exc))
