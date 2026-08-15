from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .discovery import discover
from .models import ProjectGraph
from .native_graph import execute_native_graph, plan_native_graph
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .operations import OperationError, select_component
from .sbom_providers import cyclonedx_bom_with_providers
from .spdx import spdx_document
from .uv_graph import execute_uv_graph, plan_uv_graphs


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


def _selected_static_graph(graph: ProjectGraph, selector: str | None, cargo_plans: list[object]) -> ProjectGraph:
    if selector is None:
        return graph
    try:
        selected = select_component(graph, selector)
    except OperationError as exc:
        raise ValueError(str(exc)) from exc
    keys = {selected.key(graph.root)}
    keys.update(
        getattr(plan, "component", "")
        for plan in cargo_plans
        if isinstance(getattr(plan, "component", None), str)
    )
    components = [component for component in graph.components if component.key(graph.root) in keys]
    return ProjectGraph(graph.root, components, graph.workspaces)


def _safe_spdx_uv_results(results: list[object]) -> list[object]:
    """Remove uv edges SPDX 2.3 cannot represent without losing marker semantics."""
    safe: list[object] = []
    for result in results:
        edges = [
            edge for edge in getattr(result, "edges", [])
            if not getattr(edge, "ambiguous", False) and not getattr(edge, "marker", None)
        ]
        safe.append(SimpleNamespace(
            succeeded=getattr(result, "succeeded", False),
            packages=getattr(result, "packages", []),
            edges=edges,
        ))
    return safe


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
            npm_plans = plan_npm_graphs(full_graph, selector=args.component)
            cargo_plans = plan_cargo_graphs(full_graph, selector=args.component)
            uv_plans = plan_uv_graphs(full_graph, selector=args.component)
        else:
            go_plans, npm_plans, cargo_plans, uv_plans = [], [], [], []
        graph = _selected_static_graph(full_graph, args.component, cargo_plans)
    except (OSError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    go_results = [execute_native_graph(plan) for plan in go_plans]
    npm_results = [execute_npm_graph(plan) for plan in npm_plans]
    cargo_results = [execute_cargo_graph(plan) for plan in cargo_plans]
    uv_results = [execute_uv_graph(plan) for plan in uv_plans]
    failures = [
        ("go-modules", result.plan.component, result.stderr)
        for result in go_results if not result.succeeded
    ] + [
        ("npm-lock-tree", result.plan.component, result.stderr)
        for result in npm_results if not result.succeeded
    ] + [
        ("cargo-metadata", result.plan.component, result.stderr)
        for result in cargo_results if not result.succeeded
    ] + [
        ("uv-lock", result.plan.component, result.error)
        for result in uv_results if not result.succeeded
    ]
    if failures:
        for provider, component, error in failures:
            print(f"upm: {provider} inventory failed for {component}: {error}", file=sys.stderr)
        return 1

    if args.format == "cyclonedx":
        document = cyclonedx_bom_with_providers(
            graph,
            go_results=go_results,
            npm_results=npm_results,
            cargo_results=cargo_results,
            uv_results=uv_results,
        )
    else:
        document = spdx_document(
            graph,
            go_results=go_results,
            npm_results=npm_results,
            cargo_results=cargo_results,
            uv_results=_safe_spdx_uv_results(uv_results),
        )

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
