from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .cargo_impact import analyze_cargo_impact
from .discovery import discover
from .go_offline_provider import query_native_why_offline
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .npm_impact import analyze_npm_impact
from .operations import OperationError, select_component
from .pnpm_graph import execute_pnpm_graph, plan_pnpm_graphs
from .pnpm_impact import analyze_pnpm_impact
from .provider_ownership import provider_owned_component_keys
from .python_lock_graph import plan_python_lock_graphs
from .python_lock_provider import python_lock_provider_name
from .python_lock_queries import query_python_lock_result
from .python_lock_validation import execute_validated_python_lock_graph
from .uv_graph import execute_uv_graph, plan_uv_graphs
from .uv_impact import analyze_uv_impact
from .yarn_graph import execute_yarn_graph, plan_yarn_graphs
from .yarn_impact import analyze_yarn_impact


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
        graph = discover(root)
        selected_key = None
        if args.component is not None:
            try:
                selected_key = select_component(graph, args.component).key(graph.root)
            except OperationError as exc:
                raise ValueError(str(exc)) from exc
        npm_plans = plan_npm_graphs(graph, selector=args.component)
        pnpm_plans = plan_pnpm_graphs(graph, selector=args.component)
        yarn_plans = plan_yarn_graphs(graph, selector=args.component)
        cargo_plans = plan_cargo_graphs(graph, selector=args.component)
        uv_plans = plan_uv_graphs(graph, selector=args.component)
        python_lock_plans = plan_python_lock_graphs(graph, selector=args.component)
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    answers: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    handled = provider_owned_component_keys(
        graph,
        npm_plans=npm_plans,
        pnpm_plans=pnpm_plans,
        yarn_plans=yarn_plans,
        cargo_plans=cargo_plans,
        uv_plans=uv_plans,
        python_lock_plans=python_lock_plans,
    )

    try:
        go_results, go_skips = query_native_why_offline(graph, args.package, selector=args.component)
    except ValueError as exc:
        failures.append({"provider": "go-mod-why", "component": selected_key, "error": str(exc), "returncode": None})
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

    for plan in npm_plans:
        result = execute_npm_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "npm-lock-tree", "component": plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for impact in analyze_npm_impact(result, args.package):
            answers.append({"provider": "npm-lock-tree", "scope": "logical-dependency-tree", **impact.to_dict()})

    for plan in pnpm_plans:
        result = execute_pnpm_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "pnpm-lock-tree", "component": plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for impact in analyze_pnpm_impact(result, args.package):
            answers.append({"provider": "pnpm-lock-tree", "scope": "logical-dependency-tree", **impact.to_dict()})

    for plan in yarn_plans:
        result = execute_yarn_graph(plan)
        component = plan.selected_component or plan.component
        if not result.succeeded:
            failures.append({
                "provider": "yarn-berry-resolution-graph",
                "component": component,
                "error": result.stderr,
                "returncode": result.returncode,
            })
            continue
        for impact in analyze_yarn_impact(result, args.package):
            answers.append({
                "provider": "yarn-berry-resolution-graph",
                "scope": "berry-resolution-graph",
                **impact.to_dict(),
            })

    for plan in cargo_plans:
        result = execute_cargo_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "cargo-metadata", "component": plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for impact in analyze_cargo_impact(result, args.package):
            answers.append({"provider": "cargo-metadata", "scope": "locked-offline-dependency-graph", **impact.to_dict()})

    for plan in uv_plans:
        result = execute_uv_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "uv-lock", "component": plan.component, "error": result.error, "returncode": None})
            continue
        for impact in analyze_uv_impact(result, args.package):
            answers.append({"provider": "uv-lock", "scope": "universal-lock-graph", **impact.to_dict()})

    for plan in python_lock_plans:
        result = execute_validated_python_lock_graph(graph, plan)
        provider = python_lock_provider_name(plan)
        if not result.succeeded:
            failures.append({"provider": provider, "component": plan.component, "error": result.error, "returncode": None})
            continue
        query = query_python_lock_result(result, args.package)
        if query.matched:
            answers.append(query.to_dict())

    if selected_key and (npm_plans or pnpm_plans or yarn_plans or cargo_plans or uv_plans or python_lock_plans):
        handled.add(selected_key)

    target_components = graph.components
    if selected_key is not None:
        target_components = [component for component in graph.components if component.key(graph.root) == selected_key]
    skips = [
        {
            "component": component.key(graph.root),
            "ecosystem": component.ecosystem,
            "manager": component.manager,
            "reason": "authoritative native why provider is not configured for this component",
        }
        for component in target_components
        if component.key(graph.root) not in handled
    ]
    answers.sort(key=lambda item: (
        str(item["provider"]), str(item["component"]), str(item.get("workspace_project", "")),
        str(item.get("ref", "")), str(item.get("locator", "")), str(item.get("package_id", "")),
        str(item.get("path", "")),
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
                print(f"{answer['component']} [go package-import-chain, offline]")
                print("  " + " -> ".join(answer["path"]))
            elif provider == "npm-lock-tree":
                version = f"@{answer['version']}" if answer.get("version") else ""
                print(f"{answer['component']} [npm logical-tree]: {answer['name']}{version}")
                print("  " + " -> ".join(answer["root_path"]))
            elif provider == "pnpm-lock-tree":
                version = f"@{answer['version']}" if answer.get("version") else ""
                print(f"{answer['component']} [pnpm:{answer['workspace_project']} logical-tree]: {answer['name']}{version}")
                print("  " + " -> ".join(answer["root_path"]))
                if answer.get("deduped"):
                    print("  pnpm marked this logical occurrence as deduped")
            elif provider == "yarn-berry-resolution-graph":
                marker = " [virtual]" if answer.get("virtual") else ""
                print(f"{answer['component']} [yarn-berry resolution]: {answer['locator']}{marker}")
                for path in answer.get("root_paths", []):
                    print("  " + " -> ".join(path))
            elif provider == "cargo-metadata":
                print(f"{answer['component']} [cargo locked-offline]: {answer['name']}@{answer['version']}")
                for path in answer.get("workspace_paths", []):
                    print("  " + " -> ".join(path))
            elif provider in {"poetry-lock", "pdm-lock"}:
                print(f"{answer['component']} [{provider} structured-lock]")
                for package in answer.get("packages", []):
                    certainty = "unconditional" if package.get("unconditional") else "conditional"
                    print(f"  {package['name']}@{package['version']} [{certainty}]")
                    for path in package.get("paths", []):
                        print("    " + " -> ".join(path.get("nodes", [])))
                        if path.get("markers"):
                            print("    markers: " + " && ".join(path["markers"]))
                        if path.get("optional_edges"):
                            print(f"    optional edges: {path['optional_edges']}")
                for ambiguity in answer.get("ambiguities", []):
                    candidates = ", ".join(ambiguity.get("candidate_ids", []))
                    print(f"  ? {ambiguity['source']} -> {ambiguity['dependency_name']} [ambiguous: {candidates}]")
            else:
                print(f"{answer['component']} [uv universal-lock]: {answer['name']}@{answer['version']}")
                for path in answer.get("project_paths", []):
                    print("  " + " -> ".join(path))
                if answer.get("ambiguous_references"):
                    print(f"  unresolved fork/marker references: {answer['ambiguous_references']}")
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
