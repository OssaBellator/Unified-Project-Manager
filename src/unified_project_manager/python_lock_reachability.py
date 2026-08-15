from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

from .python_lock_graph import (
    PythonLockGraphError,
    PythonLockGraphResult,
    normalize_python_name,
)


@dataclass(frozen=True)
class PythonLockPath:
    root: str
    nodes: tuple[str, ...]
    markers: tuple[str, ...]
    optional_edges: int

    @property
    def conditional(self) -> bool:
        return bool(self.markers or self.optional_edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "conditional": self.conditional,
        }


@dataclass(frozen=True)
class PythonLockReachablePackage:
    component: str
    package_id: str
    name: str
    version: str
    manager: str
    paths: tuple[PythonLockPath, ...]

    @property
    def unconditional(self) -> bool:
        return any(not path.conditional for path in self.paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "package_id": self.package_id,
            "name": self.name,
            "version": self.version,
            "manager": self.manager,
            "unconditional": self.unconditional,
            "paths": [path.to_dict() for path in self.paths],
        }


@dataclass(frozen=True)
class PythonLockAmbiguity:
    component: str
    source: str
    dependency_name: str
    candidate_ids: tuple[str, ...]
    requirement: str | None
    marker: str | None
    optional: bool
    paths: tuple[PythonLockPath, ...]

    @property
    def conditional(self) -> bool:
        return bool(self.paths) and all(path.conditional for path in self.paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "source": self.source,
            "dependency_name": self.dependency_name,
            "candidate_ids": list(self.candidate_ids),
            "requirement": self.requirement,
            "marker": self.marker,
            "optional": self.optional,
            "conditional": self.conditional,
            "paths": [path.to_dict() for path in self.paths],
        }


@dataclass(frozen=True)
class PythonLockReachabilityReport:
    query: str
    packages: tuple[PythonLockReachablePackage, ...]
    ambiguities: tuple[PythonLockAmbiguity, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "packages": [package.to_dict() for package in self.packages],
            "ambiguities": [ambiguity.to_dict() for ambiguity in self.ambiguities],
        }


def _edge_markers(edge: object) -> tuple[str, ...]:
    values: list[str] = []
    marker = getattr(edge, "marker", None)
    if isinstance(marker, str) and marker.strip():
        values.append(marker.strip())

    # Direct project requirements can arrive from normalized manifest state with
    # a PEP-508 marker still attached to the requirement text. Preserve it as a
    # condition rather than treating the direct root edge as unconditional.
    requirement = getattr(edge, "requirement", None)
    if isinstance(requirement, str) and ";" in requirement:
        _requirement, _separator, trailing = requirement.partition(";")
        if trailing.strip() and trailing.strip() not in values:
            values.append(trailing.strip())
    return tuple(values)


def _label(node: str, packages: dict[str, object]) -> str:
    package = packages.get(node)
    if package is None:
        return node
    return f"{getattr(package, 'name')}@{getattr(package, 'version')}"


def _unique_paths(paths: list[PythonLockPath]) -> tuple[PythonLockPath, ...]:
    unique = {
        (path.root, path.nodes, path.markers, path.optional_edges): path
        for path in paths
    }
    return tuple(sorted(
        unique.values(),
        key=lambda path: (
            path.conditional,
            len(path.nodes),
            path.nodes,
            path.markers,
            path.optional_edges,
        ),
    ))


def analyze_python_lock_reachability(
    result: PythonLockGraphResult,
    package_name: str,
) -> PythonLockReachabilityReport:
    """Explain structured Poetry/PDM reachability without flattening conditions.

    Resolved edges remain usable even when marker-conditional, but the markers
    and optional-edge count travel with the path. Ambiguous references never
    become graph edges; if they are themselves reachable and match the query,
    they are returned with candidate ids and the exact conditional path to the
    unresolved hop instead of manufacturing a package path.
    """
    if not result.succeeded:
        raise PythonLockGraphError(result.error)

    packages = {package.package_id: package for package in result.packages}
    forward: dict[str, list[object]] = defaultdict(list)
    for edge in result.edges:
        if edge.target_id:
            forward[edge.source_id].append(edge)
    for source in forward:
        forward[source].sort(key=lambda edge: (
            getattr(edge, "dependency_name", ""),
            getattr(edge, "target_id", "") or "",
            getattr(edge, "marker", "") or "",
        ))

    query = normalize_python_name(package_name)
    matches = {
        package.package_id: package
        for package in result.packages
        if normalize_python_name(package.name) == query
    }

    found_paths: dict[str, list[PythonLockPath]] = defaultdict(list)
    node_paths: dict[str, list[PythonLockPath]] = defaultdict(list)
    reachable_nodes: set[str] = set()

    for root in result.project_roots:
        queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], int]] = deque([
            (root, (root,), (), 0),
        ])
        # A package can have both unconditional and conditional routes, so retain
        # one shortest path for each distinct (marker-set, optional-count) state.
        visited: dict[str, set[tuple[tuple[str, ...], int]]] = defaultdict(set)
        while queue:
            current, nodes, markers, optional_edges = queue.popleft()
            state = (markers, optional_edges)
            if state in visited[current]:
                continue
            visited[current].add(state)
            reachable_nodes.add(current)
            current_path = PythonLockPath(
                root=root,
                nodes=tuple(_label(node, packages) for node in nodes),
                markers=markers,
                optional_edges=optional_edges,
            )
            node_paths[current].append(current_path)

            if current in matches:
                found_paths[current].append(current_path)
                # Continue traversal: matching package can itself lead to another
                # occurrence/candidate with the same normalized name.

            for edge in forward.get(current, []):
                target = edge.target_id
                if not target or target in nodes:
                    continue
                edge_markers = _edge_markers(edge)
                combined_markers = tuple(dict.fromkeys((*markers, *edge_markers)))
                combined_optional = optional_edges + (1 if edge.optional else 0)
                queue.append((
                    target,
                    (*nodes, target),
                    combined_markers,
                    combined_optional,
                ))

    reachable_packages: list[PythonLockReachablePackage] = []
    for package_id, package in sorted(
        matches.items(),
        key=lambda item: (item[1].version, item[0]),
    ):
        paths = found_paths.get(package_id, [])
        if not paths:
            continue
        reachable_packages.append(PythonLockReachablePackage(
            component=result.plan.component,
            package_id=package_id,
            name=package.name,
            version=package.version,
            manager=result.plan.manager,
            paths=_unique_paths(paths),
        ))

    ambiguities: list[PythonLockAmbiguity] = []
    for edge in result.edges:
        if not edge.ambiguous:
            continue
        if edge.source_id not in reachable_nodes:
            continue
        if normalize_python_name(edge.dependency_name) != query:
            continue
        ambiguity_paths: list[PythonLockPath] = []
        for source_path in node_paths.get(edge.source_id, []):
            edge_markers = _edge_markers(edge)
            markers = tuple(dict.fromkeys((*source_path.markers, *edge_markers)))
            optional_edges = source_path.optional_edges + (1 if edge.optional else 0)
            ambiguity_paths.append(PythonLockPath(
                root=source_path.root,
                nodes=(*source_path.nodes, f"?{edge.dependency_name}"),
                markers=markers,
                optional_edges=optional_edges,
            ))
        ambiguities.append(PythonLockAmbiguity(
            component=result.plan.component,
            source=_label(edge.source_id, packages),
            dependency_name=edge.dependency_name,
            candidate_ids=edge.candidate_ids,
            requirement=edge.requirement,
            marker=edge.marker,
            optional=edge.optional,
            paths=_unique_paths(ambiguity_paths),
        ))

    ambiguities.sort(key=lambda item: (
        item.source,
        normalize_python_name(item.dependency_name),
        item.candidate_ids,
        item.requirement or "",
        item.marker or "",
        item.optional,
    ))
    return PythonLockReachabilityReport(
        query=package_name,
        packages=tuple(reachable_packages),
        ambiguities=tuple(ambiguities),
    )
