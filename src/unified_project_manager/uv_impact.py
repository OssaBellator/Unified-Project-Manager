from __future__ import annotations

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


def analyze_uv_impact(result: UvGraphResult, package_name: str) -> list[UvImpact]:
    if not result.succeeded:
        raise UvGraphError(f"Cannot analyze impact for failed uv graph {result.plan.component}: {result.error}")

    packages = {package.package_id: package for package in result.packages}
    reverse: dict[str, set[str]] = defaultdict(set)
    forward: dict[str, set[str]] = defaultdict(set)
    ambiguous_by_name: dict[str, int] = defaultdict(int)
    for edge in result.edges:
        if edge.target_id:
            reverse[edge.target_id].add(edge.source_id)
            forward[edge.source_id].add(edge.target_id)
        elif edge.dependency_name.lower() == package_name.lower():
            ambiguous_by_name[edge.dependency_name.lower()] += 1

    roots = [package.package_id for package in result.packages if package.project_member]
    impacts: list[UvImpact] = []
    for target in sorted(
        (package for package in result.packages if package.name.lower() == package_name.lower()),
        key=lambda package: (package.version, package.package_id),
    ):
        direct_ids = sorted(reverse.get(target.package_id, set()))
        reachable: set[str] = set()
        queue = deque(direct_ids)
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(sorted(reverse.get(current, set()) - reachable))

        paths: list[tuple[str, ...]] = []
        for root in roots:
            if root == target.package_id:
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
                for child in sorted(forward.get(current, set())):
                    if child not in path:
                        queue_paths.append((child, (*path, child)))

        impacts.append(UvImpact(
            component=result.plan.component,
            package_id=target.package_id,
            name=target.name,
            version=target.version,
            direct_dependents=tuple(_label(packages.get(item), item) for item in direct_ids),
            transitive_dependents=tuple(sorted(_label(packages.get(item), item) for item in reachable)),
            project_paths=tuple(sorted(set(paths))),
            ambiguous_references=ambiguous_by_name.get(target.name.lower(), 0),
        ))
    return impacts
