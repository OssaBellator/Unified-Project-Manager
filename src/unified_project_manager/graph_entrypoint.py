from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .models import ProjectGraph
from .native_graph import NativeGraphError, execute_native_graph, plan_native_graph
from .npm_graph import NpmGraphError, execute_npm_graph, plan_npm_graphs
from .operations import OperationError, select_component


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm graph --native",
        description="Query authoritative native dependency graph providers",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native graph querying to one component")
    parser.add_argument("--preview", action="store_true", help="Show read-only native graph commands without executing them")
    parser.add_argument("--all-edges", action="store_true", help="For Go, include edges from non-selected source versions")
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


def native_graph_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {root}")
        graph = _selected_graph(discover(root), args.component)
        go_plans, go_skips = plan_native_graph(graph)
        npm_plans = plan_npm_graphs(graph)
    except (FileNotFoundError, NotADirectoryError, NativeGraphError, NpmGraphError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    npm_components = {plan.component for plan in npm_plans}
    skips = [skip for skip in go_skips if skip.component not in npm_components]

    if args.preview:
        plans = []
        for plan in go_plans:
            plans.append({
                "provider": "go-modules",
                **plan.to_dict(root),
                "commands": [list(plan.selected_argv), list(plan.edges_argv)],
            })
        for plan in npm_plans:
            plans.append({"provider": "npm-lock-tree", **plan.to_dict(root), "commands": [list(plan.argv)]})
        payload = {"executed": False, "plans": plans, "skips": [skip.to_dict() for skip in skips]}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in plans:
                print(f"{item['component']} [{item['provider']}]")
                for command in item["commands"]:
                    print(f"  {shlex.join(command)}")
            for skip in skips:
                print(f"- {skip.component}: skipped ({skip.reason})")
        return 0 if plans else 1

    go_results = [execute_native_graph(plan) for plan in go_plans]
    npm_results = [execute_npm_graph(plan) for plan in npm_plans]
    results = [
        {"provider": "go-modules", **result.to_dict(root)} for result in go_results
    ] + [
        {"provider": "npm-lock-tree", **result.to_dict(root)} for result in npm_results
    ]

    if args.as_json:
        print(json.dumps({"results": results, "skips": [skip.to_dict() for skip in skips]}, indent=2, sort_keys=True))
    else:
        for result in go_results:
            print(f"{result.plan.component} [go-modules]")
            if not result.succeeded:
                print(f"  x native graph failed: {result.stderr}")
                continue
            print("  selected build list:")
            for module in result.modules:
                if module.main:
                    continue
                rendered = f"{module.name} {module.version or ''}".rstrip()
                if module.replacement_name:
                    replacement = module.replacement_name
                    if module.replacement_version:
                        replacement += f" {module.replacement_version}"
                    rendered += f" => {replacement}"
                print(f"    {rendered}")
            print("  requirement edges:" + ("" if args.all_edges else " (selected source versions)"))
            for edge in result.edges:
                if not args.all_edges and not edge.source_selected:
                    continue
                source = edge.source_name + (f"@{edge.source_version}" if edge.source_version else "")
                target = edge.target_name + (f"@{edge.required_version}" if edge.required_version else "")
                selected = ""
                if edge.selected_version and edge.selected_version != edge.required_version:
                    selected = f" [selected {edge.selected_version}]"
                print(f"    {source} -> {target}{selected}")

        for result in npm_results:
            print(f"{result.plan.component} [npm-lock-tree]")
            if not result.succeeded:
                print(f"  x native graph failed: {result.stderr}")
                continue
            root_label = result.root_name or "(project root)"
            if result.root_version:
                root_label += f"@{result.root_version}"
            print(f"  root: {root_label}")
            for package in result.packages:
                indent = "    " * package.depth
                version = f"@{package.version}" if package.version else ""
                marker = " [direct]" if package.direct else ""
                print(f"{indent}{package.name}{version}{marker}")
            for problem in result.problems:
                print(f"  ! {problem}")

        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")

    all_results = [*go_results, *npm_results]
    return 0 if all_results and all(result.succeeded for result in all_results) else 1


def dispatch_graph_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "graph" or "--native" not in arguments:
        return None
    return native_graph_command(arguments[1:])
