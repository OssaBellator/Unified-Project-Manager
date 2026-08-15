from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .models import Component, ProjectGraph
from .uv_graph import UvGraphPlan, UvGraphResult, execute_uv_graph
from .uv_workspace import UvWorkspaceError, uv_workspace_ownership


class UvWorkspaceGraphError(ValueError):
    """Raised when workspace-aware uv relationship planning is ambiguous."""


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def plan_uv_workspace_graphs(graph: ProjectGraph, selector: str | None = None) -> list[UvGraphPlan]:
    try:
        roots, owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise UvWorkspaceGraphError(str(exc)) from exc
    python_components = [component for component in graph.components if component.ecosystem == "python"]
    by_path = {component.path.resolve(): component for component in python_components}

    if selector is not None:
        matches = [component for component in python_components if _matches(component, graph, selector)]
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise UvWorkspaceGraphError(f"Component selector '{selector}' is ambiguous for uv graph ingestion: {choices}")
        if not matches:
            return []
        selected = matches[0]
        owner = owners.get(selected.path.resolve())
        if owner is not None:
            root_component = by_path.get(owner.root)
            if root_component is None:
                return []
            return [UvGraphPlan(root_component.key(graph.root), owner.root / "uv.lock")]
        root_workspace = roots.get(selected.path.resolve())
        if root_workspace is not None:
            return [UvGraphPlan(selected.key(graph.root), root_workspace.root / "uv.lock")]
        if selected.manager == "uv" and "uv.lock" in selected.lockfiles:
            return [UvGraphPlan(selected.key(graph.root), selected.path / "uv.lock")]
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
    selected = tuple(plans) if plans is not None else tuple(plan_uv_workspace_graphs(graph))
    if not selected:
        return set()
    try:
        roots, _owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise UvWorkspaceGraphError(str(exc)) from exc
    result: set[str] = set()
    for plan in selected:
        root = plan.lockfile.parent.resolve()
        workspace = roots.get(root)
        if workspace is not None:
            result.update(workspace.members)
        else:
            result.add(plan.component)
    return result


def execute_uv_workspace_graph(plan: UvGraphPlan) -> UvGraphResult:
    return execute_uv_graph(plan)
