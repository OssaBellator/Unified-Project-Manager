from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .cargo_graph import CargoGraphResult, execute_cargo_graph, plan_cargo_graphs
from .go_offline_provider import execute_native_graph_offline
from .models import ProjectGraph
from .native_graph import NativeGraphResult, plan_native_graph
from .npm_graph import NpmGraphResult, execute_npm_graph, plan_npm_graphs
from .npm_sbom import NpmSbomResult, execute_npm_sbom, plan_npm_sboms
from .npm_sbom_merge import merge_npm_cyclonedx
from .pnpm_graph import PnpmGraphResult, execute_pnpm_graph, plan_pnpm_graphs
from .pnpm_sbom import PnpmSbomResult, execute_pnpm_sbom, plan_pnpm_sboms
from .pnpm_sbom_merge import merge_pnpm_cyclonedx
from .sbom_providers import cyclonedx_bom_with_providers
from .uv_graph import UvGraphResult, execute_uv_graph, plan_uv_graphs
from .yarn_graph import YarnGraphResult, execute_yarn_graph, plan_yarn_graphs
from .yarn_sbom_merge import merge_yarn_cyclonedx


class NativeCycloneDxError(ValueError):
    """Raised when requested authoritative provider inventory is incomplete."""


@dataclass
class NativeCycloneDxInventory:
    """Exact native inventory used to construct one CycloneDX document.

    The first six fields preserve the original positional constructor used by
    existing tests/integrations. New provider/path evidence is appended with
    defaults so older callers do not silently bind Cargo/uv arguments to Yarn.
    """

    bom: dict[str, Any]
    go_results: list[NativeGraphResult]
    npm_results: list[NpmSbomResult]
    pnpm_results: list[PnpmSbomResult]
    cargo_results: list[CargoGraphResult]
    uv_results: list[UvGraphResult]
    yarn_results: list[YarnGraphResult] = field(default_factory=list)
    npm_graph_results: list[NpmGraphResult] = field(default_factory=list)
    pnpm_graph_results: list[PnpmGraphResult] = field(default_factory=list)

    def provider_counts(self) -> dict[str, int]:
        return {
            "go-modules": len(self.go_results),
            "npm-native-sbom": len(self.npm_results),
            "pnpm-native-sbom": len(self.pnpm_results),
            "yarn-berry-resolution-graph": len(self.yarn_results),
            "cargo-metadata": len(self.cargo_results),
            "uv-lock": len(self.uv_results),
            "npm-path-graph": len(self.npm_graph_results),
            "pnpm-path-graph": len(self.pnpm_graph_results),
        }


def build_native_cyclonedx(
    graph: ProjectGraph,
    *,
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
    execute_npm: Callable[[object], NpmSbomResult] = execute_npm_sbom,
    execute_pnpm: Callable[[object], PnpmSbomResult] = execute_pnpm_sbom,
    execute_yarn: Callable[[object], YarnGraphResult] = execute_yarn_graph,
    execute_cargo: Callable[[object], CargoGraphResult] = execute_cargo_graph,
    execute_uv: Callable[[object], UvGraphResult] = execute_uv_graph,
    execute_npm_path: Callable[[object], NpmGraphResult] = execute_npm_graph,
    execute_pnpm_path: Callable[[object], PnpmGraphResult] = execute_pnpm_graph,
    include_path_graphs: bool = False,
) -> NativeCycloneDxInventory:
    """Build provider-backed CycloneDX without permitting network fallback.

    Go uses the GOPROXY=off wrapper, Cargo is ``--locked --offline``, npm/pnpm
    SBOMs are lockfile-only, Yarn Berry disables network and redirects install
    state to a temporary file, and uv is parsed statically. Optional npm/pnpm
    logical path graphs are collected from the same authoritative lock state for
    advisory explanations; their failure is explicit when requested.
    """

    go_plans, _go_skips = plan_native_graph(graph)
    npm_plans = plan_npm_sboms(graph, "cyclonedx")
    pnpm_plans = plan_pnpm_sboms(graph, "cyclonedx")
    yarn_plans = plan_yarn_graphs(graph)
    cargo_plans = plan_cargo_graphs(graph)
    uv_plans = plan_uv_graphs(graph)

    go_results = [execute_go(plan) for plan in go_plans]
    npm_results = [execute_npm(plan) for plan in npm_plans]
    pnpm_results = [execute_pnpm(plan) for plan in pnpm_plans]
    yarn_results = [execute_yarn(plan) for plan in yarn_plans]
    cargo_results = [execute_cargo(plan) for plan in cargo_plans]
    uv_results = [execute_uv(plan) for plan in uv_plans]

    npm_graph_results: list[NpmGraphResult] = []
    pnpm_graph_results: list[PnpmGraphResult] = []
    if include_path_graphs:
        npm_graph_results = [execute_npm_path(plan) for plan in plan_npm_graphs(graph)]
        pnpm_graph_results = [execute_pnpm_path(plan) for plan in plan_pnpm_graphs(graph)]

    failures: list[str] = []
    failures.extend(
        f"go-modules {result.plan.component}: {result.stderr}"
        for result in go_results if not result.succeeded
    )
    failures.extend(
        f"npm-native-sbom {result.plan.component}: {result.stderr}"
        for result in npm_results if not result.succeeded
    )
    failures.extend(
        f"pnpm-native-sbom {result.plan.component}: {result.stderr}"
        for result in pnpm_results if not result.succeeded
    )
    failures.extend(
        f"yarn-berry-resolution-graph {result.plan.selected_component or result.plan.component}: {result.stderr}"
        for result in yarn_results if not result.succeeded
    )
    failures.extend(
        f"cargo-metadata {result.plan.component}: {result.stderr}"
        for result in cargo_results if not result.succeeded
    )
    failures.extend(
        f"uv-lock {result.plan.component}: {result.error}"
        for result in uv_results if not result.succeeded
    )
    failures.extend(
        f"npm-path-graph {result.plan.component}: {result.stderr}"
        for result in npm_graph_results if not result.succeeded
    )
    failures.extend(
        f"pnpm-path-graph {result.plan.component}: {result.stderr}"
        for result in pnpm_graph_results if not result.succeeded
    )
    if failures:
        raise NativeCycloneDxError("Authoritative native inventory failed: " + "; ".join(failures))

    bom = cyclonedx_bom_with_providers(
        graph,
        go_results=go_results,
        npm_results=[],
        cargo_results=cargo_results,
        uv_results=uv_results,
    )
    bom = merge_npm_cyclonedx(bom, npm_results)
    bom = merge_pnpm_cyclonedx(bom, pnpm_results)
    bom = merge_yarn_cyclonedx(bom, yarn_results)
    return NativeCycloneDxInventory(
        bom=bom,
        go_results=go_results,
        npm_results=npm_results,
        pnpm_results=pnpm_results,
        cargo_results=cargo_results,
        uv_results=uv_results,
        yarn_results=yarn_results,
        npm_graph_results=npm_graph_results,
        pnpm_graph_results=pnpm_graph_results,
    )
