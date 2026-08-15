from __future__ import annotations

from collections.abc import Iterable

from .models import ProjectGraph
from .uv_graph import (
    UvGraphError,
    UvGraphPlan,
    UvGraphResult,
    execute_uv_graph,
    plan_uv_graphs,
    uv_provider_component_keys as _uv_provider_component_keys,
)


class UvWorkspaceGraphError(ValueError):
    """Compatibility error for callers of the earlier workspace helper."""


def plan_uv_workspace_graphs(graph: ProjectGraph, selector: str | None = None) -> list[UvGraphPlan]:
    """Compatibility alias for the now workspace-aware main uv graph planner."""
    try:
        return plan_uv_graphs(graph, selector=selector)
    except UvGraphError as exc:
        raise UvWorkspaceGraphError(str(exc)) from exc


def uv_provider_component_keys(
    graph: ProjectGraph,
    plans: Iterable[UvGraphPlan] | None = None,
) -> set[str]:
    """Compatibility alias for the main uv provider ownership helper."""
    try:
        return _uv_provider_component_keys(graph, plans)
    except UvGraphError as exc:
        raise UvWorkspaceGraphError(str(exc)) from exc


def execute_uv_workspace_graph(plan: UvGraphPlan) -> UvGraphResult:
    return execute_uv_graph(plan)
