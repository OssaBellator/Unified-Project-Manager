from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .models import ProjectGraph
from .python_lock_graph import PythonLockGraphPlan, PythonLockGraphResult
from .python_lock_provider import (
    execute_python_lock_provider,
    python_lock_provider_name,
    suppress_python_lock_static_inventory,
)
from .python_lock_sbom import merge_python_lock_cyclonedx
from .sbom import cyclonedx_bom


class PythonLockNativeInventoryError(ValueError):
    """Raised when authoritative Poetry/PDM inventory cannot be constructed."""


@dataclass
class PythonLockNativeInventory:
    """Exact structured-lock evidence used to construct one CycloneDX document."""

    bom: dict[str, Any]
    plans: list[PythonLockGraphPlan]
    results: list[PythonLockGraphResult]

    @property
    def applicable(self) -> bool:
        return bool(self.plans)

    def provider_counts(self) -> dict[str, int]:
        counts = {"poetry-lock": 0, "pdm-lock": 0}
        for plan in self.plans:
            counts[python_lock_provider_name(plan)] += 1
        return counts


def assemble_python_lock_native_inventory(
    graph: ProjectGraph,
    plans: Iterable[PythonLockGraphPlan],
    results: Iterable[PythonLockGraphResult],
) -> PythonLockNativeInventory:
    """Assemble a fail-closed exact BOM while retaining its lock-graph evidence."""

    plan_list = list(plans)
    result_list = list(results)
    expected = [(plan.component, plan.manager, plan.lockfile) for plan in plan_list]
    actual = [
        (result.plan.component, result.plan.manager, result.plan.lockfile)
        for result in result_list
    ]
    if actual != expected:
        raise PythonLockNativeInventoryError(
            "Structured Python lock inventory results do not match the planned provider order."
        )

    failures = [
        f"{python_lock_provider_name(result.plan)} {result.plan.component}: {result.error or 'provider failed'}"
        for result in result_list
        if not result.succeeded
    ]
    if failures:
        raise PythonLockNativeInventoryError(
            "Authoritative structured Python lock inventory failed: " + "; ".join(failures)
        )

    prepared_graph = suppress_python_lock_static_inventory(graph, plan_list)
    bom = merge_python_lock_cyclonedx(cyclonedx_bom(prepared_graph), result_list)
    return PythonLockNativeInventory(bom=bom, plans=plan_list, results=result_list)


def build_python_lock_native_inventory(
    graph: ProjectGraph,
    *,
    selector: str | None = None,
) -> PythonLockNativeInventory:
    """Build exact Poetry/PDM CycloneDX plus retained path evidence without subprocesses, network, or mutation."""

    plans, results = execute_python_lock_provider(graph, selector=selector)
    return assemble_python_lock_native_inventory(graph, plans, results)
