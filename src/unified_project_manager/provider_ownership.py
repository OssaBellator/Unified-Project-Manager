from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .cargo_graph import CargoGraphPlan, cargo_provider_component_keys
from .models import ProjectGraph
from .npm_graph import NpmGraphPlan, npm_provider_component_keys
from .pnpm_graph import PnpmGraphPlan, pnpm_provider_component_keys
from .python_lock_graph import PythonLockGraphPlan
from .python_lock_provider import python_lock_owned_component_keys
from .uv_graph import UvGraphPlan, uv_provider_component_keys
from .yarn_graph import YarnGraphPlan, yarn_provider_component_keys


def _npm_owned_component_keys(graph: ProjectGraph, plans: tuple[NpmGraphPlan, ...]) -> set[str]:
    result: set[str] = set()
    broad = tuple(plan for plan in plans if plan.workspace_selector is None)
    if broad:
        result.update(npm_provider_component_keys(graph, broad))
    by_path = {component.path.resolve(): component for component in graph.components}
    for plan in plans:
        if plan.workspace_selector is None:
            continue
        result.add(plan.component)
        selector = plan.workspace_selector
        relative = selector[2:] if selector.startswith("./") else selector
        selected_path = (plan.cwd / Path(relative)).resolve()
        component = by_path.get(selected_path)
        if component is not None:
            result.add(component.key(graph.root))
    return result


def provider_owned_component_keys(
    graph: ProjectGraph,
    *,
    npm_plans: Iterable[NpmGraphPlan] = (),
    pnpm_plans: Iterable[PnpmGraphPlan] = (),
    yarn_plans: Iterable[YarnGraphPlan] = (),
    cargo_plans: Iterable[CargoGraphPlan] = (),
    uv_plans: Iterable[UvGraphPlan] = (),
    python_lock_plans: Iterable[PythonLockGraphPlan] = (),
) -> set[str]:
    """Return discovered component keys served by non-Go relationship providers.

    Workspace-aware providers may serve more components than the provider plan's
    root component. This helper is deliberately plan-based so CLI skip accounting,
    status coverage, and selector promotion share one ownership truth. Structured
    Poetry/PDM providers are component-owned but use the same plan-derived path so
    public routing and status cannot disagree about coverage.
    """
    npm = tuple(npm_plans)
    pnpm = tuple(pnpm_plans)
    yarn = tuple(yarn_plans)
    cargo = tuple(cargo_plans)
    uv = tuple(uv_plans)
    python_lock = tuple(python_lock_plans)
    result = _npm_owned_component_keys(graph, npm)
    result.update(pnpm_provider_component_keys(graph, pnpm))
    result.update(yarn_provider_component_keys(graph, yarn))
    result.update(cargo_provider_component_keys(graph, cargo))
    result.update(uv_provider_component_keys(graph, uv))
    result.update(python_lock_owned_component_keys(python_lock))
    return result
