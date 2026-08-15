from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .discovery import discover
from .go_offline_provider import execute_native_graph_offline
from .models import ProjectGraph
from .native_graph import plan_native_graph
from .npm_sbom import NpmSbomError, execute_npm_sbom, plan_npm_sboms
from .npm_sbom_merge import merge_npm_cyclonedx, merge_npm_spdx
from .operations import OperationError, select_component
from .pnpm_sbom import PnpmSbomError, execute_pnpm_sbom, plan_pnpm_sboms
from .pnpm_sbom_merge import merge_pnpm_cyclonedx, merge_pnpm_spdx
from .python_lock_graph import plan_python_lock_graphs
from .python_lock_provider import python_lock_provider_name, suppress_python_lock_static_inventory
from .python_lock_sbom import merge_python_lock_cyclonedx, merge_python_lock_spdx
from .python_lock_validation import execute_validated_python_lock_graph
from .sbom_providers import cyclonedx_bom_with_providers
from .spdx import spdx_document
from .uv_graph import UvGraphError, execute_uv_graph, plan_uv_graphs
from .yarn_graph import YarnGraphError, execute_yarn_graph, plan_yarn_graphs
from .yarn_sbom_merge import merge_yarn_cyclonedx, merge_yarn_spdx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm sbom",
        description="Export CycloneDX or SPDX, optionally enriched by authoritative native relationship providers",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--format", choices=("cyclonedx", "spdx"), default="cyclonedx")
    parser.add_argument("--component", help="Limit native enrichment to one component where supported")
    parser.add_argument("--output", help="Write the SBOM to a file instead of stdout")
    parser.add_argument("--native", action="store_true", help="Enrich relationships using authoritative native providers")
    return parser


def _selected_static_graph(
    graph: ProjectGraph,
    selector: str | None,
    cargo_plans: list[object],
    uv_plans: list[object],
    python_lock_plans: list[object],
) -> ProjectGraph:
    if selector is None:
        return suppress_python_lock_static_inventory(graph, python_lock_plans)
    try:
        selected = select_component(graph, selector)
    except OperationError as exc:
        raise ValueError(str(exc)) from exc
    selected_key = selected.key(graph.root)
    keys = {selected_key}
    keys.update(
        getattr(plan, "component", "")
        for plan in cargo_plans
        if isinstance(getattr(plan, "component", None), str)
    )
    components = [component for component in graph.components if component.key(graph.root) in keys]

    # A selected uv component may be backed by a shared workspace lock at a
    # different directory. In native mode the authoritative uv provider owns
    # registry package identity/scope, so do not seed the selected component's
    # SBOM with an unscoped static parse of the whole shared uv.lock.
    selected_uv = any(
        getattr(plan, "selected_component", None) == selected_key
        for plan in uv_plans
    )
    if selected_uv:
        components = [
            replace(component, resolved_packages=[])
            if component.key(graph.root) == selected_key and component.ecosystem == "python"
            else component
            for component in components
        ]
    selected_graph = ProjectGraph(graph.root, components, graph.workspaces)
    return suppress_python_lock_static_inventory(selected_graph, python_lock_plans)


def sbom_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"upm: project path is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        full_graph = discover(root)
        if args.native:
            go_plans, _go_skips = plan_native_graph(full_graph, selector=args.component)
            npm_plans = plan_npm_sboms(full_graph, args.format, selector=args.component)
            pnpm_plans = plan_pnpm_sboms(full_graph, args.format, selector=args.component)
            yarn_plans = plan_yarn_graphs(full_graph, selector=args.component)
            cargo_plans = plan_cargo_graphs(full_graph, selector=args.component)
            uv_plans = plan_uv_graphs(full_graph, selector=args.component)
            python_lock_plans = plan_python_lock_graphs(full_graph, selector=args.component)
        else:
            go_plans, npm_plans, pnpm_plans, yarn_plans, cargo_plans, uv_plans, python_lock_plans = [], [], [], [], [], [], []
        graph = _selected_static_graph(full_graph, args.component, cargo_plans, uv_plans, python_lock_plans)
    except (OSError, NpmSbomError, PnpmSbomError, YarnGraphError, UvGraphError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    go_results = [execute_native_graph_offline(plan) for plan in go_plans]
    npm_results = [execute_npm_sbom(plan) for plan in npm_plans]
    pnpm_results = [execute_pnpm_sbom(plan) for plan in pnpm_plans]
    yarn_results = [execute_yarn_graph(plan) for plan in yarn_plans]
    cargo_results = [execute_cargo_graph(plan) for plan in cargo_plans]
    uv_results = [execute_uv_graph(plan) for plan in uv_plans]
    python_lock_results = [execute_validated_python_lock_graph(full_graph, plan) for plan in python_lock_plans]
    failures = [
        ("go-modules", result.plan.component, result.stderr)
        for result in go_results if not result.succeeded
    ] + [
        ("npm-native-sbom", result.plan.component, result.stderr)
        for result in npm_results if not result.succeeded
    ] + [
        ("pnpm-native-sbom", result.plan.component, result.stderr)
        for result in pnpm_results if not result.succeeded
    ] + [
        ("yarn-berry-resolution-graph", result.plan.selected_component or result.plan.component, result.stderr)
        for result in yarn_results if not result.succeeded
    ] + [
        ("cargo-metadata", result.plan.component, result.stderr)
        for result in cargo_results if not result.succeeded
    ] + [
        ("uv-lock", result.plan.component, result.error)
        for result in uv_results if not result.succeeded
    ] + [
        (python_lock_provider_name(result.plan), result.plan.component, result.error)
        for result in python_lock_results if not result.succeeded
    ]
    if failures:
        for provider, component, error in failures:
            print(f"upm: {provider} inventory failed for {component}: {error}", file=sys.stderr)
        return 1

    try:
        if args.format == "cyclonedx":
            document = cyclonedx_bom_with_providers(
                graph,
                go_results=go_results,
                npm_results=[],
                cargo_results=cargo_results,
                uv_results=uv_results,
            )
            document = merge_npm_cyclonedx(document, npm_results)
            document = merge_pnpm_cyclonedx(document, pnpm_results)
            document = merge_yarn_cyclonedx(document, yarn_results)
            document = merge_python_lock_cyclonedx(document, python_lock_results)
        else:
            document = spdx_document(
                graph,
                go_results=go_results,
                npm_results=[],
                cargo_results=cargo_results,
                uv_results=uv_results,
            )
            document = merge_npm_spdx(document, npm_results)
            document = merge_pnpm_spdx(document, pnpm_results)
            document = merge_yarn_spdx(document, yarn_results)
            document = merge_python_lock_spdx(document, python_lock_results)
    except (NpmSbomError, PnpmSbomError, YarnGraphError, UvGraphError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output).expanduser()
        if target.exists() and target.is_dir():
            print(f"upm: SBOM output path is a directory: {target}", file=sys.stderr)
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(str(target))
    else:
        print(rendered, end="")
    return 0


def _requests_spdx(arguments: list[str]) -> bool:
    if "--format=spdx" in arguments:
        return True
    try:
        index = arguments.index("--format")
    except ValueError:
        return False
    return index + 1 < len(arguments) and arguments[index + 1] == "spdx"


def dispatch_sbom_provider_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "sbom":
        return None
    if "--native" not in arguments and not _requests_spdx(arguments):
        return None
    return sbom_command(arguments[1:])
