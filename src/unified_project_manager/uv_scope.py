from __future__ import annotations

import re
from collections import defaultdict, deque

from .uv_graph import UvGraphError, UvGraphResult


def normalize_uv_project_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def uv_project_root_ids(result: UvGraphResult) -> list[str]:
    """Return project-package roots represented by a uv result.

    Unscoped shared-lock results expose every project member. A component-scoped
    plan must map the selected pyproject identity to exactly one locked project
    package; ambiguity is an error rather than a reason to broaden to siblings.
    """
    members = [package for package in result.packages if package.project_member]
    selected_name = result.plan.selected_project_name
    if result.plan.selected_component is None:
        return [package.package_id for package in members]
    if not selected_name:
        raise UvGraphError(
            f"Selected uv workspace component {result.plan.selected_component} has no project name; "
            "shared-lock scope cannot be established safely."
        )
    target = normalize_uv_project_name(selected_name)
    candidates = [package for package in members if normalize_uv_project_name(package.name) == target]
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


def uv_forward_edges(result: UvGraphResult) -> dict[str, set[str]]:
    forward: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        if edge.target_id:
            forward[edge.source_id].add(edge.target_id)
    return forward


def uv_scope_package_ids(result: UvGraphResult) -> set[str]:
    """Return package IDs belonging to the requested uv project/workspace scope.

    A whole-workspace/project result keeps all packages in the authoritative
    universal lock. A selected workspace member keeps only packages reachable
    from that member's locked project node. Marker-bearing resolved edges remain
    part of package inventory reachability; downstream SBOM encoders still decide
    whether a conditional relationship can be represented safely.
    """
    if not result.succeeded:
        raise UvGraphError(f"Cannot scope failed uv graph {result.plan.component}: {result.error}")
    if result.plan.selected_component is None:
        return {package.package_id for package in result.packages}

    roots = uv_project_root_ids(result)
    forward = uv_forward_edges(result)
    reachable: set[str] = set()
    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(sorted(forward.get(current, set()) - reachable))
    return reachable
