from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cargo_graph import CargoGraphError, execute_cargo_graph, plan_cargo_graphs
from .cargo_impact import analyze_cargo_impact
from .discovery import discover
from .go_offline_provider import execute_native_graph_offline
from .native_graph import NativeGraphError, plan_native_graph
from .native_impact import analyze_native_impact
from .npm_graph import NpmGraphError, execute_npm_graph, plan_npm_graphs
from .npm_impact import analyze_npm_impact
from .pnpm_graph import PnpmGraphError, execute_pnpm_graph, plan_pnpm_graphs
from .pnpm_impact import analyze_pnpm_impact
from .uv_graph import UvGraphError, execute_uv_graph, plan_uv_graphs
from .uv_impact import analyze_uv_impact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm impact --native",
        description="Analyze dependency impact from authoritative native graph providers",
    )
    parser.add_argument("package")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native impact analysis to one component")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def impact_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {root}")
        graph = discover(root)
        go_plans, go_skips = plan_native_graph(graph, selector=args.component)
        npm_plans = plan_npm_graphs(graph, selector=args.component)
        pnpm_plans = plan_pnpm_graphs(graph, selector=args.component)
        cargo_plans = plan_cargo_graphs(graph, selector=args.component)
        uv_plans = plan_uv_graphs(graph, selector=args.component)
    except (
        FileNotFoundError,
        NotADirectoryError,
        NativeGraphError,
        NpmGraphError,
        PnpmGraphError,
        CargoGraphError,
        UvGraphError,
        ValueError,
    ) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    handled_components = {plan.component for plan in [*npm_plans, *pnpm_plans, *cargo_plans, *uv_plans]}
    skips = [skip for skip in go_skips if skip.component not in handled_components]
    impacts: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for plan in go_plans:
        result = execute_native_graph_offline(plan)
        if not result.succeeded:
            failures.append({"provider": "go-modules", "component": plan.component, "returncode": result.returncode, "error": result.stderr})
            continue
        for impact in analyze_native_impact(result, args.package):
            impacts.append({"provider": "go-modules", "scope": "module-requirement", **impact.to_dict()})

    for plan in npm_plans:
        result = execute_npm_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "npm-lock-tree", "component": plan.component, "returncode": result.returncode, "error": result.stderr})
            continue
        for impact in analyze_npm_impact(result, args.package):
            impacts.append({"provider": "npm-lock-tree", "scope": "logical-dependency-tree", **impact.to_dict()})

    for plan in pnpm_plans:
        result = execute_pnpm_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "pnpm-lock-tree", "component": plan.component, "returncode": result.returncode, "error": result.stderr})
            continue
        for impact in analyze_pnpm_impact(result, args.package):
            impacts.append({"provider": "pnpm-lock-tree", "scope": "logical-dependency-tree", **impact.to_dict()})

    for plan in cargo_plans:
        result = execute_cargo_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "cargo-metadata", "component": plan.component, "returncode": result.returncode, "error": result.stderr})
            continue
        for impact in analyze_cargo_impact(result, args.package):
            impacts.append({"provider": "cargo-metadata", "scope": "locked-offline-dependency-graph", **impact.to_dict()})

    for plan in uv_plans:
        result = execute_uv_graph(plan)
        if not result.succeeded:
            failures.append({"provider": "uv-lock", "component": plan.component, "returncode": None, "error": result.error})
            continue
        for impact in analyze_uv_impact(result, args.package):
            impacts.append({"provider": "uv-lock", "scope": "universal-lock-graph", **impact.to_dict()})

    impacts.sort(key=lambda item: (
        str(item["provider"]), str(item["component"]), str(item.get("project", "")),
        str(item.get("ref", "")), str(item.get("module", "")), str(item.get("package_id", "")),
    ))
    if args.as_json:
        print(json.dumps({
            "query": args.package,
            "impacts": impacts,
            "failures": failures,
            "skips": [skip.to_dict() for skip in skips],
        }, indent=2, sort_keys=True))
    else:
        print("Impact is dependency-graph impact only; it is not source/API/runtime reachability.")
        for impact in impacts:
            if impact["provider"] == "go-modules":
                rendered = f"{impact['component']} [go]: {impact['module']}"
                if impact.get("effective_name") != impact.get("module"):
                    rendered += f" => {impact['effective_name']}"
                if impact.get("selected_version"):
                    rendered += f" {impact['selected_version']}"
                print(rendered)
                for path in impact.get("root_paths", []):
                    print("  root path: " + " -> ".join(path))
            elif impact["provider"] == "npm-lock-tree":
                version = f"@{impact['version']}" if impact.get("version") else ""
                print(f"{impact['component']} [npm]: {impact['name']}{version}")
                print("  logical path: " + " -> ".join(impact["root_path"]))
            elif impact["provider"] == "pnpm-lock-tree":
                version = f"@{impact['version']}" if impact.get("version") else ""
                print(f"{impact['component']} [pnpm:{impact['project']}]: {impact['name']}{version}")
                print("  logical path: " + " -> ".join(impact["root_path"]))
                if impact.get("deduped"):
                    print("  pnpm marked this logical occurrence as deduped")
            elif impact["provider"] == "cargo-metadata":
                print(f"{impact['component']} [cargo]: {impact['name']}@{impact['version']}")
                for path in impact.get("workspace_paths", []):
                    print("  workspace path: " + " -> ".join(path))
            else:
                print(f"{impact['component']} [uv]: {impact['name']}@{impact['version']}")
                for path in impact.get("project_paths", []):
                    print("  project path: " + " -> ".join(path))
                if impact.get("ambiguous_references"):
                    print(f"  unresolved fork/marker references: {impact['ambiguous_references']}")
        for failure in failures:
            print(f"x {failure['component']} [{failure['provider']}]: {failure['error']}")
        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")

    if failures:
        return 1
    return 0 if impacts else 1


def dispatch_impact_provider_command(arguments: list[str]) -> int | None:
    if not arguments or "--native" not in arguments:
        return None
    if arguments[0] == "impact":
        return impact_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "projects" and arguments[1] == "impact":
        from .fleet_impact_provider_entrypoint import fleet_impact_command

        return fleet_impact_command(arguments[2:])
    return None
