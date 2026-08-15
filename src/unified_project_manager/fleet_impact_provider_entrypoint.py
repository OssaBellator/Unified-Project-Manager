from __future__ import annotations

import argparse
import json
import sys

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .cargo_impact import analyze_cargo_impact
from .discovery import discover
from .go_offline_provider import execute_native_graph_offline
from .native_graph import plan_native_graph
from .native_impact import analyze_native_impact
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .npm_impact import analyze_npm_impact
from .pnpm_graph import execute_pnpm_graph, plan_pnpm_graphs
from .pnpm_impact import analyze_pnpm_impact
from .registry import RegistryError, registered_paths
from .uv_graph import execute_uv_graph, plan_uv_graphs
from .uv_impact import analyze_uv_impact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm projects impact --native",
        description="Analyze dependency-graph impact across registered projects",
    )
    parser.add_argument("package")
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def fleet_impact_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    impacts: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    skips: list[dict[str, object]] = []
    missing: list[str] = []
    try:
        roots = registered_paths(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    for root in roots:
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            graph = discover(root)
            go_plans, go_skips = plan_native_graph(graph)
            npm_plans = plan_npm_graphs(graph)
            pnpm_plans = plan_pnpm_graphs(graph)
            cargo_plans = plan_cargo_graphs(graph)
            uv_plans = plan_uv_graphs(graph)
        except (OSError, ValueError) as exc:
            failures.append({"project": str(root), "provider": None, "component": None, "error": str(exc), "returncode": None})
            continue

        handled_components = {plan.component for plan in [*npm_plans, *pnpm_plans, *cargo_plans, *uv_plans]}
        for skip in go_skips:
            if skip.component not in handled_components:
                skips.append({"project": str(root), **skip.to_dict()})

        for plan in go_plans:
            result = execute_native_graph_offline(plan)
            if not result.succeeded:
                failures.append({
                    "project": str(root), "provider": "go-modules", "component": plan.component,
                    "error": result.stderr, "returncode": result.returncode,
                })
                continue
            for impact in analyze_native_impact(result, args.package):
                impacts.append({
                    "project": str(root), "provider": "go-modules", "scope": "module-requirement",
                    **impact.to_dict(),
                })

        for plan in npm_plans:
            result = execute_npm_graph(plan)
            if not result.succeeded:
                failures.append({
                    "project": str(root), "provider": "npm-lock-tree", "component": plan.component,
                    "error": result.stderr, "returncode": result.returncode,
                })
                continue
            for impact in analyze_npm_impact(result, args.package):
                impacts.append({
                    "project": str(root), "provider": "npm-lock-tree", "scope": "logical-dependency-tree",
                    **impact.to_dict(),
                })

        for plan in pnpm_plans:
            result = execute_pnpm_graph(plan)
            if not result.succeeded:
                failures.append({
                    "project": str(root), "provider": "pnpm-lock-tree", "component": plan.component,
                    "error": result.stderr, "returncode": result.returncode,
                })
                continue
            for impact in analyze_pnpm_impact(result, args.package):
                impacts.append({
                    "project": str(root), "provider": "pnpm-lock-tree", "scope": "logical-dependency-tree",
                    **impact.to_dict(),
                })

        for plan in cargo_plans:
            result = execute_cargo_graph(plan)
            if not result.succeeded:
                failures.append({
                    "project": str(root), "provider": "cargo-metadata", "component": plan.component,
                    "error": result.stderr, "returncode": result.returncode,
                })
                continue
            for impact in analyze_cargo_impact(result, args.package):
                impacts.append({
                    "project": str(root), "provider": "cargo-metadata", "scope": "locked-offline-dependency-graph",
                    **impact.to_dict(),
                })

        for plan in uv_plans:
            result = execute_uv_graph(plan)
            if not result.succeeded:
                failures.append({
                    "project": str(root), "provider": "uv-lock", "component": plan.component,
                    "error": result.error, "returncode": None,
                })
                continue
            for impact in analyze_uv_impact(result, args.package):
                impacts.append({
                    "project": str(root), "provider": "uv-lock", "scope": "universal-lock-graph",
                    **impact.to_dict(),
                })

    impacts.sort(key=lambda item: (
        str(item["project"]), str(item["provider"]), str(item["component"]),
        str(item.get("workspace_project", "")), str(item.get("ref", "")),
        str(item.get("module", "")), str(item.get("package_id", "")),
    ))
    affected_projects = sorted({str(item["project"]) for item in impacts})

    if args.as_json:
        print(json.dumps({
            "query": args.package,
            "affected_projects": len(affected_projects),
            "projects": affected_projects,
            "impacts": impacts,
            "failures": failures,
            "skips": skips,
            "missing": missing,
        }, indent=2, sort_keys=True))
    else:
        print("Impact is dependency-graph impact across registered projects; it is not source/API/runtime reachability.")
        if not impacts:
            print(f"No supported native graph selected {args.package!r}.")
        for impact in impacts:
            if impact["provider"] == "go-modules":
                rendered = f"{impact['project']} [{impact['component']}] [go/offline]: {impact['module']}"
                if impact.get("selected_version"):
                    rendered += f" {impact['selected_version']}"
                print(rendered)
                for path in impact.get("root_paths", []):
                    print("  root path: " + " -> ".join(path))
            elif impact["provider"] == "npm-lock-tree":
                version = f"@{impact['version']}" if impact.get("version") else ""
                print(f"{impact['project']} [{impact['component']}] [npm]: {impact['name']}{version}")
                print("  logical path: " + " -> ".join(impact["root_path"]))
            elif impact["provider"] == "pnpm-lock-tree":
                version = f"@{impact['version']}" if impact.get("version") else ""
                workspace_project = impact.get("workspace_project", ".")
                print(f"{impact['project']} [{impact['component']}] [pnpm:{workspace_project}]: {impact['name']}{version}")
                print("  logical path: " + " -> ".join(impact["root_path"]))
            elif impact["provider"] == "cargo-metadata":
                print(f"{impact['project']} [{impact['component']}] [cargo]: {impact['name']}@{impact['version']}")
                for path in impact.get("workspace_paths", []):
                    print("  workspace path: " + " -> ".join(path))
            else:
                print(f"{impact['project']} [{impact['component']}] [uv]: {impact['name']}@{impact['version']}")
                for path in impact.get("project_paths", []):
                    print("  project path: " + " -> ".join(path))
                if impact.get("ambiguous_references"):
                    print(f"  unresolved fork/marker references: {impact['ambiguous_references']}")
        for failure in failures:
            print(f"x {failure['project']} [{failure.get('component') or 'project'}]: {failure['error']}")
        if missing:
            print(f"Skipped {len(missing)} missing registered project(s).")

    if failures:
        return 1
    return 0 if impacts else 1


def dispatch_fleet_impact_provider_command(arguments: list[str]) -> int | None:
    if len(arguments) < 2 or arguments[0] != "projects" or arguments[1] != "impact" or "--native" not in arguments:
        return None
    return fleet_impact_command(arguments[2:])
