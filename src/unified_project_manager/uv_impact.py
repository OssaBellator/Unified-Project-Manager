from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

from .uv_graph import UvGraphError, UvGraphResult


@dataclass(frozen=True)
class UvImpact:
    component: str
    package_id: str
    name: str
    version: str
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    project_paths: tuple[tuple[str, ...], ...]
    ambiguous_references: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label(package: object | None, fallback: str) -> str:
    if package is None:
        return fallback
    name = getattr(package, "name", None)
    version = getattr(package, "version", None)
    if isinstance(name, str) and isinstance(version, str):
        return f"{name}@{version}"
    return fallback


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _project_roots(result: UvGraphResult) -> list[str]:
    members = [package for package in result.packages if package.project_member]
    selected_name = result.plan.selected_project_name
    if result.plan.selected_component is None:
        return [package.package_id for package in members]
    if not selected_name:
        raise UvGraphError(
            f"Selected uv workspace component {result.plan.selected_component} has no project name; "
            "shared-lock impact cannot be scoped safely."
        )
    target = _normalized_name(selected_name)
    candidates = [package for package in members if _normalized_name(package.name) == target]
    selected_version = result.plan.selected_project_version
    if selected_version:
        candidates = [package for package in candidates if package.version == selected_version]
    if len(candidates) != 1:
        rendered = ", ".join(f"{package.name}@{package.version}" for package in candidates) or "none"
        raise UvGraphError(
            f"Selected uv workspace component {result.plan.selected_component} does not map to exactly one "
            f"project package in {result.plan.lockfile}: {rendered}."
        )
    return [candidates[0].package_id]


def _forward_reachable(roots: list[str], forward: dict[str, set[str]]) -> set[str]:
    reachable: set[str] = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(sorted(forward.get(current, set()) - reachable))
    return reachable


def analyze_uv_impact(result: UvGraphResult, package_name: str) -> list[UvImpact]:
    if not result.succeeded:
        raise UvGraphError(f"Cannot analyze impact for failed uv graph {result.plan.component}: {result.error}")

    packages = {package.package_id: package for package in result.packages}
    reverse: dict[str, set[str]] = defaultdict(set)
    forward: dict[str, set[str]] = defaultdict(set)
    ambiguous_edges = []
    for edge in result.edges:
        if edge.target_id:
            reverse[edge.target_id].add(edge.source_id)
            forward[edge.source_id].add(edge.target_id)
        elif edge.dependency_name.lower() == package_name.lower():
            ambiguous_edges.append(edge)

    roots = _project_roots(result)
    scoped = result.plan.selected_component is not None
    allowed = _forward_reachable(roots, forward) if scoped else set(packages)
    impacts: list[UvImpact] = []
    for target in sorted(
        (package for package in result.packages if package.name.lower() == package_name.lower()),
        key=lambda package: (package.version, package.package_id),
    ):
        if scoped and target.package_id not in allowed:
            continue
        direct_ids = sorted(reverse.get(target.package_id, set()) & allowed)
        reachable: set[str] = set()
        queue = deque(direct_ids)
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(sorted((reverse.get(current, set()) & allowed) - reachable))

        paths: list[tuple[str, ...]] = []
        for root in roots:
            if root == target.package_id:
                paths.append((_label(packages.get(root), root),))
                continue
            queue_paths: deque[tuple[str, tuple[str, ...]]] = deque([(root, (root,))])
            visited: set[str] = set()
            while queue_paths:
                current, path = queue_paths.popleft()
                if current in visited:
                    continue
                visited.add(current)
                if current == target.package_id:
                    paths.append(tuple(_label(packages.get(item), item) for item in path))
                    break
                for child in sorted(forward.get(current, set()) & allowed):
                    if child not in path:
                        queue_paths.append((child, (*path, child)))

        ambiguous_count = sum(
            1 for edge in ambiguous_edges
            if not scoped or edge.source_id in allowed
        )
        impacts.append(UvImpact(
            component=result.plan.selected_component or result.plan.component,
            package_id=target.package_id,
            name=target.name,
            version=target.version,
            direct_dependents=tuple(_label(packages.get(item), item) for item in direct_ids),
            transitive_dependents=tuple(sorted(_label(packages.get(item), item) for item in reachable)),
            project_paths=tuple(sorted(set(paths))),
            ambiguous_references=ambiguous_count,
        ))
    return impacts
