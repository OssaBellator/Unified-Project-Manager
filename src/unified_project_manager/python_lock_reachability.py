from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
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
    ambiguous_hops: int = 0

    @property
    def conditional(self) -> bool:
        return bool(self.markers or self.optional_edges)

    @property
    def possible(self) -> bool:
        return self.ambiguous_hops > 0

    @property
    def certainty(self) -> str:
        if self.possible:
            return "possible"
        if self.conditional:
            return "conditional"
        return "unconditional"

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "nodes": list(self.nodes),
            "markers": list(self.markers),
            "optional_edges": self.optional_edges,
            "ambiguous_hops": self.ambiguous_hops,
            "conditional": self.conditional,
            "possible": self.possible,
            "certainty": self.certainty,
        }


@dataclass(frozen=True)
class PythonLockReachablePackage:
    component: str
    package_id: str
    name: str
    version: str
    manager: str
    paths: tuple[PythonLockPath, ...]
    paths_truncated: bool = False

    @property
    def unconditional(self) -> bool:
        return any(not path.conditional and not path.possible for path in self.paths)

    @property
    def possible(self) -> bool:
        return bool(self.paths) and all(path.possible for path in self.paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "package_id": self.package_id,
            "name": self.name,
            "version": self.version,
            "manager": self.manager,
            "unconditional": self.unconditional,
            "possible": self.possible,
            "paths_truncated": self.paths_truncated,
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
    paths_truncated: bool = False

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
            "paths_truncated": self.paths_truncated,
            "paths": [path.to_dict() for path in self.paths],
        }


@dataclass(frozen=True)
class PythonLockReachabilityReport:
    query: str
    packages: tuple[PythonLockReachablePackage, ...]
    possible_packages: tuple[PythonLockReachablePackage, ...]
    ambiguities: tuple[PythonLockAmbiguity, ...]
    search_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "search_truncated": self.search_truncated,
            "packages": [package.to_dict() for package in self.packages],
            "possible_packages": [package.to_dict() for package in self.possible_packages],
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


def _unique_paths(paths: list[PythonLockPath]) -> list[PythonLockPath]:
    unique = {
        (path.root, path.nodes, path.markers, path.optional_edges, path.ambiguous_hops): path
        for path in paths
    }
    return sorted(
        unique.values(),
        key=lambda path: (
            path.possible,
            path.conditional,
            len(path.nodes),
            path.nodes,
            path.markers,
            path.optional_edges,
            path.ambiguous_hops,
        ),
    )


def _bounded_paths(
    paths: list[PythonLockPath],
    max_paths: int,
    *,
    search_truncated: bool,
) -> tuple[tuple[PythonLockPath, ...], bool]:
    ordered = _unique_paths(paths)
    truncated = search_truncated or len(ordered) > max_paths
    return tuple(ordered[:max_paths]), truncated


def analyze_python_lock_reachability(
    result: PythonLockGraphResult,
    package_name: str,
    *,
    max_paths_per_package: int = 64,
    max_search_states: int = 10000,
) -> PythonLockReachabilityReport:
    """Explain Poetry/PDM reachability without flattening uncertainty.

    Resolved paths retain marker/optional conditions. Reachable ambiguous edges
    are expanded conservatively through *all* candidate branches as possible
    paths, with an explicit ``?dependency`` hop before each candidate. This keeps
    public why/impact/advisory evidence aligned with the possible inventory that
    native SBOM scanning intentionally admits.

    Traversal is path-sensitive so distinct parent chains are not collapsed.
    Explicit path and search budgets prevent pathological graphs from turning a
    query into unbounded work; truncation is surfaced instead of hidden.
    """
    if not result.succeeded:
        raise PythonLockGraphError(result.error)
    if max_paths_per_package < 1:
        raise PythonLockGraphError("max_paths_per_package must be at least 1")
    if max_search_states < 1:
        raise PythonLockGraphError("max_search_states must be at least 1")

    packages = {package.package_id: package for package in result.packages}
    outgoing: dict[str, list[object]] = defaultdict(list)
    for edge in result.edges:
        outgoing[edge.source_id].append(edge)
    for source in outgoing:
        outgoing[source].sort(key=lambda edge: (
            normalize_python_name(getattr(edge, "dependency_name", "")),
            getattr(edge, "target_id", "") or "",
            tuple(getattr(edge, "candidate_ids", ()) or ()),
            getattr(edge, "marker", "") or "",
            bool(getattr(edge, "optional", False)),
        ))

    query = normalize_python_name(package_name)
    matching_ids = {
        package.package_id
        for package in result.packages
        if normalize_python_name(package.name) == query
    }

    resolved_paths: dict[str, list[PythonLockPath]] = defaultdict(list)
    possible_paths: dict[str, list[PythonLockPath]] = defaultdict(list)
    ambiguity_paths: dict[
        tuple[str, str, tuple[str, ...], str | None, str | None, bool],
        list[PythonLockPath],
    ] = defaultdict(list)

    # current-id, visited package ids, rendered path, markers, optional count,
    # number of ambiguity hops traversed.
    queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int]] = deque()
    for root in result.project_roots:
        queue.append((root, (root,), (root,), (), 0, 0))

    seen_exact_states: set[
        tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int]
    ] = set()
    processed_states = 0
    search_truncated = False

    while queue:
        if processed_states >= max_search_states:
            search_truncated = True
            break
        state = queue.popleft()
        if state in seen_exact_states:
            continue
        seen_exact_states.add(state)
        processed_states += 1

        current, visited_ids, rendered_nodes, markers, optional_edges, ambiguous_hops = state
        current_path = PythonLockPath(
            root=rendered_nodes[0],
            nodes=rendered_nodes,
            markers=markers,
            optional_edges=optional_edges,
            ambiguous_hops=ambiguous_hops,
        )
        if current in matching_ids:
            target = possible_paths if ambiguous_hops else resolved_paths
            target[current].append(current_path)

        for edge in outgoing.get(current, []):
            edge_markers = _edge_markers(edge)
            combined_markers = tuple(dict.fromkeys((*markers, *edge_markers)))
            combined_optional = optional_edges + (1 if getattr(edge, "optional", False) else 0)
            target_id = getattr(edge, "target_id", None)
            if isinstance(target_id, str) and target_id:
                if target_id in visited_ids:
                    continue
                queue.append((
                    target_id,
                    (*visited_ids, target_id),
                    (*rendered_nodes, _label(target_id, packages)),
                    combined_markers,
                    combined_optional,
                    ambiguous_hops,
                ))
                continue

            if not bool(getattr(edge, "ambiguous", False)):
                continue

            dependency_name = getattr(edge, "dependency_name", "")
            candidate_ids = tuple(
                candidate
                for candidate in (getattr(edge, "candidate_ids", ()) or ())
                if isinstance(candidate, str) and candidate in packages
            )
            ambiguity_hops = ambiguous_hops + 1
            ambiguity_path = PythonLockPath(
                root=rendered_nodes[0],
                nodes=(*rendered_nodes, f"?{dependency_name}"),
                markers=combined_markers,
                optional_edges=combined_optional,
                ambiguous_hops=ambiguity_hops,
            )
            if normalize_python_name(dependency_name) == query:
                ambiguity_key = (
                    current,
                    dependency_name,
                    candidate_ids,
                    getattr(edge, "requirement", None),
                    getattr(edge, "marker", None),
                    bool(getattr(edge, "optional", False)),
                )
                ambiguity_paths[ambiguity_key].append(ambiguity_path)

            for candidate_id in candidate_ids:
                if candidate_id in visited_ids:
                    continue
                queue.append((
                    candidate_id,
                    (*visited_ids, candidate_id),
                    (*ambiguity_path.nodes, _label(candidate_id, packages)),
                    combined_markers,
                    combined_optional,
                    ambiguity_hops,
                ))

    reachable_packages: list[PythonLockReachablePackage] = []
    possible_packages: list[PythonLockReachablePackage] = []
    for package_id in sorted(
        matching_ids,
        key=lambda value: (packages[value].version, value),
    ):
        package = packages[package_id]
        paths = resolved_paths.get(package_id, [])
        if paths:
            bounded, truncated = _bounded_paths(
                paths, max_paths_per_package, search_truncated=search_truncated,
            )
            reachable_packages.append(PythonLockReachablePackage(
                component=result.plan.component,
                package_id=package_id,
                name=package.name,
                version=package.version,
                manager=result.plan.manager,
                paths=bounded,
                paths_truncated=truncated,
            ))
        paths = possible_paths.get(package_id, [])
        if paths:
            bounded, truncated = _bounded_paths(
                paths, max_paths_per_package, search_truncated=search_truncated,
            )
            possible_packages.append(PythonLockReachablePackage(
                component=result.plan.component,
                package_id=package_id,
                name=package.name,
                version=package.version,
                manager=result.plan.manager,
                paths=bounded,
                paths_truncated=truncated,
            ))

    ambiguities: list[PythonLockAmbiguity] = []
    for key, paths in ambiguity_paths.items():
        source_id, dependency_name, candidate_ids, requirement, marker, optional = key
        bounded, truncated = _bounded_paths(
            paths, max_paths_per_package, search_truncated=search_truncated,
        )
        ambiguities.append(PythonLockAmbiguity(
            component=result.plan.component,
            source=_label(source_id, packages),
            dependency_name=dependency_name,
            candidate_ids=candidate_ids,
            requirement=requirement,
            marker=marker,
            optional=optional,
            paths=bounded,
            paths_truncated=truncated,
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
        possible_packages=tuple(possible_packages),
        ambiguities=tuple(ambiguities),
        search_truncated=search_truncated,
    )
