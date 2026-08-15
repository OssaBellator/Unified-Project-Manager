from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .discovery import discover
from .native_graph import execute_native_graph, plan_native_graph
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .sbom_providers import cyclonedx_bom_with_providers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm sbom --native",
        description="Export CycloneDX enriched by authoritative native inventory/relationship providers",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--format", choices=("cyclonedx",), default="cyclonedx")
    parser.add_argument("--component", help="Limit native enrichment to one component where supported")
    parser.add_argument("--output", help="Write the SBOM to a file instead of stdout")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _selected_graph(graph, selector: str | None):
    if selector is None:
        return graph
    from .operations import OperationError, select_component
    from .models import ProjectGraph

    try:
        component = select_component(graph, selector)
    except OperationError as exc:
        raise ValueError(str(exc)) from exc
    return ProjectGraph(graph.root, [component], graph.workspaces)


def native_sbom_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"upm: project path is not a directory: {root}", file=sys.stderr)
        return 2
    try:
        graph = _selected_graph(discover(root), args.component)
        go_plans, _go_skips = plan_native_graph(graph)
        npm_plans = plan_npm_graphs(graph)
        cargo_plans = plan_cargo_graphs(graph)
    except (OSError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    go_results = [execute_native_graph(plan) for plan in go_plans]
    npm_results = [execute_npm_graph(plan) for plan in npm_plans]
    cargo_results = [execute_cargo_graph(plan) for plan in cargo_plans]
    failures = [
        ("go-modules", result.plan.component, result.stderr)
        for result in go_results if not result.succeeded
    ] + [
        ("npm-lock-tree", result.plan.component, result.stderr)
        for result in npm_results if not result.succeeded
    ] + [
        ("cargo-metadata", result.plan.component, result.stderr)
        for result in cargo_results if not result.succeeded
    ]
    if failures:
        for provider, component, error in failures:
            print(f"upm: {provider} inventory failed for {component}: {error}", file=sys.stderr)
        return 1

    bom = cyclonedx_bom_with_providers(
        graph,
        go_results=go_results,
        npm_results=npm_results,
        cargo_results=cargo_results,
    )
    rendered = json.dumps(bom, indent=2, sort_keys=True) + "\n"
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


def dispatch_sbom_provider_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "sbom" or "--native" not in arguments:
        return None
    return native_sbom_command(arguments[1:])
