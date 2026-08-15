from __future__ import annotations

from collections.abc import Iterable

from .cargo_graph import CargoGraphPlan, cargo_provider_component_keys
from .models import ProjectGraph
from .npm_graph import NpmGraphPlan, npm_provider_component_keys
from .pnpm_graph import PnpmGraphPlan, pnpm_provider_component_keys


def provider_owned_component_keys(
    graph: ProjectGraph,
    *,
    npm_plans: Iterable[NpmGraphPlan] = (),
    pnpm_plans: Iterable[PnpmGraphPlan] = (),
    cargo_plans: Iterable[CargoGraphPlan] = (),
    uv_plans: Iterable[object] = (),
) -> set[str]:
    """Return discovered component keys served by non-Go relationship providers.

    Workspace-aware providers may serve more components than the plan's owner
    component. This helper is intentionally plan-based so CLI skip accounting,
    status coverage, and selector promotion can share the same ownership truth.
    """
    npm = tuple(npm_plans)
    pnpm = tuple(pnpm_plans)
    cargo = tuple(cargo_plans)
    result = set()
    result.update(npm_provider_component_keys(graph, npm))
    result.update(pnpm_provider_component_keys(graph, pnpm))
    result.update(cargo_provider_component_keys(graph, cargo))
    result.update(
        component
        for plan in uv_plans
        for component in [getattr(plan, "component", None)]
        if isinstance(component, str)
    )
    return result
