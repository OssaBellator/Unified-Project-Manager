from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .cargo_graph import CargoGraphError, execute_cargo_graph, plan_cargo_graphs
from .discovery import discover
from .go_offline_provider import execute_native_graph_offline
from .native_graph import NativeGraphError, plan_native_graph
from .npm_graph import NpmGraphError, execute_npm_graph, plan_npm_graphs
from .pnpm_graph import PnpmGraphError, execute_pnpm_graph, plan_pnpm_graphs
from .provider_ownership import provider_owned_component_keys
from .uv_graph import UvGraphError, execute_uv_graph, plan_uv_graphs
from .yarn_execution_policy import yarn_execution_guards
from .yarn_graph import YarnGraphError, execute_yarn_graph, plan_yarn_graphs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm graph --native",
        description="Query authoritative native dependency graph providers",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native graph querying to one component")
    parser.add_argument("--preview", action="store_true", help="Show read-only native graph commands/sources without executing them")
    parser.add_argument("--all-edges", action="store_true", help="For Go, include edges from non-selected source versions")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def native_graph_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {root}")
        graph = discover(root)
        go_plans, go_skips = plan_native_graph(graph, selector=args.component)
        npm_plans = plan_npm_graphs(graph, selector=args.component)
        pnpm_plans = plan_pnpm_graphs(graph, selector=args.component)
        yarn_plans = plan_yarn_graphs(graph, selector=args.component)
        cargo_plans = plan_cargo_graphs(graph, selector=args.component)
        uv_plans = plan_uv_graphs(graph, selector=args.component)
    except (
        FileNotFoundError,
        NotADirectoryError,
        NativeGraphError,
        NpmGraphError,
        PnpmGraphError,
        YarnGraphError,
        CargoGraphError,
        UvGraphError,
        ValueError,
    ) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    handled_components = provider_owned_component_keys(
        graph,
        npm_plans=npm_plans,
        pnpm_plans=pnpm_plans,
        yarn_plans=yarn_plans,
        cargo_plans=cargo_plans,
        uv_plans=uv_plans,
    )
    skips = [skip for skip in go_skips if skip.component not in handled_components]

    if args.preview:
        plans = []
        for plan in go_plans:
            plans.append({
                "provider": "go-modules",
                **plan.to_dict(root),
                "commands": [list(plan.selected_argv), list(plan.edges_argv)],
                "network": "offline",
            })
        for plan in npm_plans:
            plans.append({"provider": "npm-lock-tree", **plan.to_dict(root), "commands": [list(plan.argv)]})
        for plan in pnpm_plans:
            plans.append({"provider": "pnpm-lock-tree", **plan.to_dict(root), "commands": [list(plan.argv)]})
        for plan in yarn_plans:
            plans.append({
                "provider": "yarn-berry-resolution-graph",
                **plan.to_dict(root),
                "commands": [list(plan.argv)],
                "execution_guards": yarn_execution_guards(),
            })
        for plan in cargo_plans:
            plans.append({"provider": "cargo-metadata", **plan.to_dict(root), "commands": [list(plan.argv)]})
        for plan in uv_plans:
            plans.append({"provider": "uv-lock", **plan.to_dict(root), "commands": []})
        payload = {"executed": False, "plans": plans, "skips": [skip.to_dict() for skip in skips]}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in plans:
                print(f"{item['component']} [{item['provider']}]")
                if item["commands"]:
                    for command in item["commands"]:
                        print(f"  {shlex.join(command)}")
                else:
                    print(f"  static source: {item.get('lockfile', item.get('source', 'native state'))}")
            for skip in skips:
                print(f"- {skip.component}: skipped ({skip.reason})")
        return 0 if plans else 1

    go_results = [execute_native_graph_offline(plan) for plan in go_plans]
    npm_results = [execute_npm_graph(plan) for plan in npm_plans]
    pnpm_results = [execute_pnpm_graph(plan) for plan in pnpm_plans]
    yarn_results = [execute_yarn_graph(plan) for plan in yarn_plans]
    cargo_results = [execute_cargo_graph(plan) for plan in cargo_plans]
    uv_results = [execute_uv_graph(plan) for plan in uv_plans]
    results = [
        {"provider": "go-modules", **result.to_dict(root)} for result in go_results
    ] + [
        {"provider": "npm-lock-tree", **result.to_dict(root)} for result in npm_results
    ] + [
        {"provider": "pnpm-lock-tree", **result.to_dict(root)} for result in pnpm_results
    ] + [
        {"provider": "yarn-berry-resolution-graph", **result.to_dict(root)} for result in yarn_results
    ] + [
        {"provider": "cargo-metadata", **result.to_dict(root)} for result in cargo_results
    ] + [
        {"provider": "uv-lock", **result.to_dict(root)} for result in uv_results
    ]

    if args.as_json:
        print(json.dumps({"results": results, "skips": [skip.to_dict() for skip in skips]}, indent=2, sort_keys=True))
    else:
        for result in go_results:
            print(f"{result.plan.component} [go-modules]")
            if not result.succeeded:
                print(f"  x offline native graph failed: {result.stderr}")
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
            scope = f" workspace={result.plan.workspace_selector}" if result.plan.workspace_selector else ""
            print(f"  root: {root_label}{scope}")
            for package in result.packages:
                indent = "    " * package.depth
                version = f"@{package.version}" if package.version else ""
                marker = " [direct]" if package.direct else ""
                print(f"{indent}{package.name}{version}{marker}")
            for problem in result.problems:
                print(f"  ! {problem}")

        for result in pnpm_results:
            print(f"{result.plan.component} [pnpm-lock-tree]")
            if not result.succeeded:
                print(f"  x lock-only native graph failed: {result.stderr}")
                continue
            by_project: dict[str, list[object]] = {}
            for package in result.packages:
                by_project.setdefault(package.project_ref, []).append(package)
            for project in result.projects:
                label = project.name or project.path or "(project root)"
                if project.version:
                    label += f"@{project.version}"
                print(f"  project: {label} [{project.path}]")
                for package in sorted(by_project.get(project.ref, []), key=lambda item: item.ref):
                    indent = "    " * package.depth
                    version = f"@{package.version}" if package.version else ""
                    alias = f" as {package.alias}" if package.alias != package.name else ""
                    flags = []
                    if package.direct:
                        flags.append(package.scope)
                    if package.deduped:
                        flags.append("deduped")
                    marker = f" [{' '.join(flags)}]" if flags else ""
                    print(f"{indent}{package.name}{version}{alias}{marker}")

        for result in yarn_results:
            component = result.plan.selected_component or result.plan.component
            print(f"{component} [yarn-berry-resolution-graph]")
            if not result.succeeded:
                print(f"  x isolated native graph failed: {result.stderr}")
                continue
            print(f"  Yarn {result.yarn_version or 'unknown'}; network disabled; temporary install state")
            print("  locator packages:")
            for package in result.packages:
                flags = []
                if package.project_member:
                    flags.append("workspace")
                if package.virtual:
                    flags.append("virtual")
                marker = f" [{' '.join(flags)}]" if flags else ""
                print(f"    {package.locator}{marker}")
            print("  resolution edges:")
            for edge in result.edges:
                kind = "" if edge.kind == "dependency" else f" [{edge.kind}]"
                print(f"    {edge.source_locator} -> {edge.target_locator}{kind}")

        for result in cargo_results:
            print(f"{result.plan.component} [cargo-metadata]")
            if not result.succeeded:
                print(f"  x native graph failed: {result.stderr}")
                continue
            packages = {package.package_id: package for package in result.packages}
            print("  locked offline package graph:")
            for package in result.packages:
                marker = " [workspace]" if package.workspace_member else ""
                print(f"    {package.name}@{package.version}{marker}")
            print("  dependency edges:")
            for edge in result.edges:
                source = packages.get(edge.source_id)
                target = packages.get(edge.target_id)
                source_label = f"{source.name}@{source.version}" if source else edge.source_id
                target_label = f"{target.name}@{target.version}" if target else edge.target_id
                kinds = ",".join(edge.kinds)
                print(f"    {source_label} -> {target_label} [{kinds}]")

        for result in uv_results:
            print(f"{result.plan.component} [uv-lock]")
            if not result.succeeded:
                print(f"  x uv.lock graph failed: {result.error}")
                continue
            packages = {package.package_id: package for package in result.packages}
            print("  universal lock packages:")
            for package in result.packages:
                marker = " [project]" if package.project_member else ""
                print(f"    {package.name}@{package.version}{marker}")
            print("  dependency edges:")
            for edge in result.edges:
                source = packages.get(edge.source_id)
                source_label = f"{source.name}@{source.version}" if source else edge.source_id
                marker = f" if {edge.marker}" if edge.marker else ""
                if edge.target_id:
                    target = packages.get(edge.target_id)
                    target_label = f"{target.name}@{target.version}" if target else edge.target_id
                    print(f"    {source_label} -> {target_label}{marker}")
                else:
                    candidates = ", ".join(edge.candidate_ids) or "none"
                    print(f"    {source_label} -> {edge.dependency_name}{marker} [ambiguous candidates: {candidates}]")

        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")

    all_results = [*go_results, *npm_results, *pnpm_results, *yarn_results, *cargo_results, *uv_results]
    return 0 if all_results and all(result.succeeded for result in all_results) else 1


def dispatch_graph_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "graph" or "--native" not in arguments:
        return None
    return native_graph_command(arguments[1:])
