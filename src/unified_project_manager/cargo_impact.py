from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

from .cargo_graph import CargoGraphError, CargoGraphResult


@dataclass(frozen=True)
class CargoImpact:
    component: str
    package_id: str
    name: str
    version: str
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    workspace_paths: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_cargo_impact(result: CargoGraphResult, crate: str) -> list[CargoImpact]:
    """Analyze reverse Cargo dependency reachability for every matching crate version."""
    if not result.succeeded:
        raise CargoGraphError(
            f"Cannot analyze impact for failed Cargo graph {result.plan.component}: {result.stderr}"
        )

    packages = {package.package_id: package for package in result.packages}
    reverse: dict[str, set[str]] = defaultdict(set)
    forward: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        reverse[edge.target_id].add(edge.source_id)
        forward[edge.source_id].add(edge.target_id)

    roots = [package.package_id for package in result.packages if package.workspace_member]
    if result.resolve_root and result.resolve_root not in roots:
        roots.append(result.resolve_root)

    impacts: list[CargoImpact] = []
    for target in sorted(
        (package for package in result.packages if package.name == crate),
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
        for root_id in roots:
            if root_id == target.package_id:
                continue
            queue_paths: deque[tuple[str, tuple[str, ...]]] = deque([(root_id, (root_id,))])
            visited: set[str] = set()
            while queue_paths:
                current, path = queue_paths.popleft()
                if current in visited:
                    continue
                visited.add(current)
                if current == target.package_id:
                    labels = tuple(_label(packages.get(item), item) for item in path)
                    paths.append(labels)
                    break
                for child in sorted(forward.get(current, set())):
                    if child not in path:
                        queue_paths.append((child, (*path, child)))

        impacts.append(CargoImpact(
            component=result.plan.component,
            package_id=target.package_id,
            name=target.name,
            version=target.version,
            direct_dependents=tuple(_label(packages.get(item), item) for item in direct_ids),
            transitive_dependents=tuple(sorted(_label(packages.get(item), item) for item in reachable)),
            workspace_paths=tuple(sorted(set(paths))),
        ))
    return impacts


def _label(package: object | None, fallback: str) -> str:
    if package is None:
        return fallback
    name = getattr(package, "name", None)
    version = getattr(package, "version", None)
    if isinstance(name, str) and isinstance(version, str):
        return f"{name}@{version}"
    return fallback
