from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .cargo_impact import analyze_cargo_impact
from .discovery import discover
from .models import ProjectGraph
from .native_graph import query_native_why
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .npm_impact import analyze_npm_impact
from .operations import OperationError, select_component


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm why --native",
        description="Ask authoritative native providers why a dependency is present",
    )
    parser.add_argument("package")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native why analysis to one component")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _selected_graph(graph: ProjectGraph, selector: str | None) -> ProjectGraph:
    if selector is None:
        return graph
    try:
        component = select_component(graph, selector)
    except OperationError as exc:
        raise ValueError(str(exc)) from exc
    return ProjectGraph(graph.root, [component], graph.workspaces)


def why_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        message = f"project path is not a directory: {root}"
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2
    try:
        graph = _selected_graph(discover(root), args.component)
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    answers: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    handled: set[str] = set()

    go_components = [component for component in graph.components if component.ecosystem == "go"]
    if go_components:
        try:
            go_results, go_skips = query_native_why(graph, args.package)
        except ValueError as exc:
            failures.append({"provider": "go-mod-why", "component": None, "error": str(exc), "returncode": None})
            go_results, go_skips = [], []
        for result in go_results:
            handled.add(result.component)
            if not result.succeeded:
                failures.append({"provider": "go-mod-why", "component": result.component, "error": result.stderr, "returncode": result.returncode})
            elif result.needed:
                answers.append({
                    "provider": "go-mod-why",
                    "scope": "package-import-chain",
                    "component": result.component,
                    "query": args.package,
                    "path": list(result.path),
                })
        for skip in go_skips:
            if skip.ecosystem == "go":
                handled.add(skip.component)

    npm_plans = plan_npm_graphs(graph)
    for plan in npm_plans:
        handled.add(plan.component)
        result = execute_npm_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "npm-lock-tree", "component": plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for impact in analyze_npm_impact(result, args.package):
            answers.append({
                "provider": "npm-lock-tree",
                "scope": "logical-dependency-tree",
                **impact.to_dict(),
            })

    cargo_plans = plan_cargo_graphs(graph)
    for plan in cargo_plans:
        handled.add(plan.component)
        result = execute_cargo_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "cargo-metadata", "component": plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for impact in analyze_cargo_impact(result, args.package):
            answers.append({
                "provider": "cargo-metadata",
                "scope": "locked-offline-dependency-graph",
                **impact.to_dict(),
            })

    skips = [
        {
            "component": component.key(graph.root),
            "ecosystem": component.ecosystem,
            "manager": component.manager,
            "reason": "authoritative native why provider is not configured for this component",
        }
        for component in graph.components
        if component.key(graph.root) not in handled
    ]
    answers.sort(key=lambda item: (
        str(item["provider"]), str(item["component"]), str(item.get("ref", "")),
        str(item.get("package_id", "")), str(item.get("path", "")),
    ))

    if args.as_json:
        print(json.dumps({
            "query": args.package,
            "answers": answers,
            "failures": failures,
            "skips": skips,
        }, indent=2, sort_keys=True))
    else:
        for answer in answers:
            provider = answer["provider"]
            if provider == "go-mod-why":
                print(f"{answer['component']} [go package-import-chain]")
                print("  " + " -> ".join(answer["path"]))
            elif provider == "npm-lock-tree":
                version = f"@{answer['version']}" if answer.get("version") else ""
                print(f"{answer['component']} [npm logical-tree]: {answer['name']}{version}")
                print("  " + " -> ".join(answer["root_path"]))
            else:
                print(f"{answer['component']} [cargo locked-offline]: {answer['name']}@{answer['version']}")
                for path in answer.get("workspace_paths", []):
                    print("  " + " -> ".join(path))
        for failure in failures:
            print(f"x {failure.get('component') or 'provider'} [{failure['provider']}]: {failure['error']}")
        for skip in skips:
            print(f"- {skip['component']}: skipped ({skip['reason']})")

    if failures:
        return 1
    return 0 if answers else 1


def dispatch_why_provider_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "why" or "--native" not in arguments:
        return None
    return why_command(arguments[1:])
