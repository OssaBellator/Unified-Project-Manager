from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any

from .yarn_graph import YarnGraphError, YarnGraphResult


@dataclass(frozen=True)
class YarnImpact:
    component: str
    locator: str
    name: str
    version: str | None
    protocol: str | None
    virtual: bool
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    root_paths: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_yarn_impact(result: YarnGraphResult, package_name: str) -> list[YarnImpact]:
    """Return dependency-graph impact paths while preserving Yarn locator identity."""
    if not result.succeeded:
        raise YarnGraphError(
            f"Cannot analyze impact for failed Yarn graph {result.plan.component}: {result.stderr}"
        )

    packages = {package.locator: package for package in result.packages}
    forward: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        if edge.source_locator not in packages or edge.target_locator not in packages:
            continue
        forward[edge.source_locator].add(edge.target_locator)
        reverse[edge.target_locator].add(edge.source_locator)

    roots = sorted(package.locator for package in result.packages if package.project_member)
    impacts: list[YarnImpact] = []
    for target in sorted(
        (package for package in result.packages if package.name.lower() == package_name.lower()),
        key=lambda package: (package.version or "", package.locator),
    ):
        direct = tuple(sorted(reverse.get(target.locator, set())))
        transitive: set[str] = set()
        queue = deque(direct)
        while queue:
            current = queue.popleft()
            if current in transitive:
                continue
            transitive.add(current)
            queue.extend(sorted(reverse.get(current, set()) - transitive))

        paths: list[tuple[str, ...]] = []
        for root in roots:
            if root == target.locator:
                paths.append((root,))
                continue
            queue_paths: deque[tuple[str, tuple[str, ...]]] = deque([(root, (root,))])
            visited: set[str] = set()
            while queue_paths:
                current, path = queue_paths.popleft()
                if current in visited:
                    continue
                visited.add(current)
                if current == target.locator:
                    paths.append(path)
                    break
                for child in sorted(forward.get(current, set())):
                    if child not in path:
                        queue_paths.append((child, (*path, child)))

        # Packages not reachable from a project/workspace root are not impact
        # answers. Yarn may expose devirtualized backing locators and other
        # project-wide records that aren't active from the selected scope.
        if not paths and target.locator not in roots:
            continue

        impacts.append(YarnImpact(
            component=result.plan.selected_component or result.plan.component,
            locator=target.locator,
            name=target.name,
            version=target.version,
            protocol=target.protocol,
            virtual=target.virtual,
            direct_dependents=direct,
            transitive_dependents=tuple(sorted(transitive)),
            root_paths=tuple(sorted(set(paths))),
        ))
    return impacts
