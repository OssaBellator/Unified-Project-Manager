from __future__ import annotations

from collections import defaultdict, deque

from .yarn_graph import YarnGraphError, YarnGraphResult


def yarn_scope_locators(result: YarnGraphResult) -> set[str]:
    """Return Yarn locators reachable from active workspace/project roots.

    `yarn info --all --recursive` can expose the project's stored package set.
    That is useful graph evidence, but a stored record is not automatically a
    package used by an active workspace. SBOM/audit package identity therefore
    follows only dependency/devirtualization edges reachable from workspace
    locators. This mirrors `analyze_yarn_impact` and prevents stale/orphan stored
    resolutions from becoming scan targets merely because Yarn reported them.
    """
    if not result.succeeded:
        raise YarnGraphError(
            f"Cannot scope failed Yarn graph {result.plan.component}: {result.stderr}"
        )

    packages = {package.locator: package for package in result.packages}
    roots = sorted(
        package.locator
        for package in result.packages
        if package.project_member
    )
    if not roots:
        raise YarnGraphError(
            f"Yarn graph {result.plan.selected_component or result.plan.component} contains no workspace/project root locator."
        )

    forward: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        if edge.source_locator in packages and edge.target_locator in packages:
            forward[edge.source_locator].add(edge.target_locator)

    reachable: set[str] = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(sorted(forward.get(current, set()) - reachable))
    return reachable
