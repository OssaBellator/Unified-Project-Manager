from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Protocol

from .models import ProjectGraph

PYTHON_LOCK_SCOPE = "structured-lock-dependency-graph"


class PythonLockPlanLike(Protocol):
    component: str
    manager: str


def python_lock_provider_name(manager_or_plan: str | PythonLockPlanLike) -> str:
    manager = manager_or_plan if isinstance(manager_or_plan, str) else manager_or_plan.manager
    if manager == "poetry":
        return "poetry-lock"
    if manager == "pdm":
        return "pdm-lock"
    raise ValueError(f"Unsupported structured Python lock manager: {manager!r}")


def python_lock_owned_component_keys(plans: Iterable[PythonLockPlanLike]) -> set[str]:
    return {plan.component for plan in plans}


def suppress_python_lock_static_inventory(
    graph: ProjectGraph,
    plans: Iterable[PythonLockPlanLike],
) -> ProjectGraph:
    """Remove generic lock package observations for structured-provider owners.

    The Python adapter intentionally records every package in poetry.lock/pdm.lock
    as generic static inventory. Native structured-lock mode must not seed an
    SBOM from that looser observation because it would reintroduce unreachable or
    ambiguous packages that the validated reachability provider excluded.
    """

    owned = python_lock_owned_component_keys(plans)
    if not owned:
        return graph
    components = [
        replace(component, resolved_packages=[])
        if component.key(graph.root) in owned
        else component
        for component in graph.components
    ]
    return ProjectGraph(graph.root, components, graph.workspaces)


def execute_python_lock_provider(
    graph: ProjectGraph,
    *,
    selector: str | None = None,
) -> tuple[list[Any], list[Any]]:
    """Plan and execute validated Poetry/PDM lock graphs without side effects.

    Imports are intentionally local so provider naming/static-inventory policy can
    be tested without loading the TOML graph implementation.
    """

    from .python_lock_graph import plan_python_lock_graphs
    from .python_lock_validation import execute_validated_python_lock_graph

    plans = plan_python_lock_graphs(graph, selector=selector)
    results = [execute_validated_python_lock_graph(graph, plan) for plan in plans]
    return plans, results
