from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .go_workspace import WorkspaceError, execute_workspace_inspection, plan_workspace_inspection
from .native_impact import analyze_native_impact
from .workspace_graph import execute_workspace_graph, plan_workspace_graph


def _list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm workspaces", description="List discovered workspace manifests")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm workspace inspect", description="Inspect a Go workspace using go work edit -json")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--workspace", help="Workspace key or relative path when multiple workspaces exist")
    parser.add_argument("--preview", action="store_true", help="Show the authoritative read-only inspection command without executing it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _graph_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm workspace graph", description="Query a Go workspace selected build list and module requirement graph")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--workspace", help="Workspace key or relative path when multiple workspaces exist")
    parser.add_argument("--preview", action="store_true", help="Show native read-only graph commands without executing them")
    parser.add_argument("--all-edges", action="store_true", help="Include requirement edges from non-selected source versions")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _impact_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm workspace impact", description="Analyze module-requirement impact inside a Go workspace")
    parser.add_argument("module")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--workspace", help="Workspace key or relative path when multiple workspaces exist")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _existing_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def list_workspaces_command(argv: list[str]) -> int:
    args = _list_parser().parse_args(argv)
    try:
        graph = discover(_existing_root(args.path))
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    rows = [workspace.to_dict(graph.root) for workspace in graph.workspaces]
    if args.as_json:
        print(json.dumps({"workspaces": rows}, indent=2, sort_keys=True))
    elif not rows:
        print("No supported workspace manifests found.")
    else:
        for row in rows:
            state = ",".join(row["lockfiles"]) or "none"
            print(
                f"{row['key']} manager={row['manager'] or 'unknown'} "
                f"manifest={','.join(row['manifests'])} state={state}"
            )
    return 0


def inspect_workspace_command(argv: list[str]) -> int:
    args = _inspect_parser().parse_args(argv)
    try:
        graph = discover(_existing_root(args.path))
        plan = plan_workspace_inspection(graph, args.workspace)
    except (FileNotFoundError, NotADirectoryError, OSError, WorkspaceError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.preview:
        payload = {"executed": False, "plan": plan.to_dict(graph.root)}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"{plan.workspace}: {shlex.join(plan.argv)}")
        return 0

    result = execute_workspace_inspection(graph, plan)
    if args.as_json:
        print(json.dumps(result.to_dict(graph.root), indent=2, sort_keys=True))
    elif not result.succeeded:
        print(f"x {plan.workspace}: {result.stderr}")
    else:
        print(
            f"Workspace: {plan.workspace} | Go {result.go_version or 'unspecified'} | "
            f"toolchain {result.toolchain or 'default'}"
        )
        for use in result.uses or []:
            scope = "project" if use.in_project else "external"
            component = f" [{use.component}]" if use.component else ""
            print(f"  use {use.disk_path} -> {use.resolved_path} ({scope}){component}")
        for replacement in result.replacements or []:
            old = replacement.old_path + (f"@{replacement.old_version}" if replacement.old_version else "")
            new = replacement.new_path + (f"@{replacement.new_version}" if replacement.new_version else "")
            print(f"  replace {old} => {new}")
    return 0 if result.succeeded else 1


def workspace_graph_command(argv: list[str]) -> int:
    args = _graph_parser().parse_args(argv)
    try:
        graph = discover(_existing_root(args.path))
        plan = plan_workspace_graph(graph, args.workspace)
    except (FileNotFoundError, NotADirectoryError, OSError, WorkspaceError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.preview:
        payload = {
            "executed": False,
            "plan": plan.to_dict(graph.root),
            "environment": {
                "GOWORK": str(plan.cwd / "go.work"),
                "GOFLAGS_add": "-mod=readonly",
            },
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"{plan.component}: {shlex.join(plan.selected_argv)}")
            print(f"{plan.component}: {shlex.join(plan.edges_argv)}")
            print(f"GOWORK={plan.cwd / 'go.work'}; module updates disabled")
        return 0

    result = execute_workspace_graph(plan)
    if args.as_json:
        print(json.dumps(result.to_dict(graph.root), indent=2, sort_keys=True))
    elif not result.succeeded:
        print(f"x {plan.component}: {result.stderr}")
    else:
        print(plan.component)
        print("  selected workspace build list:")
        for module in result.modules:
            rendered = module.name + (f" {module.version}" if module.version else "")
            if module.main:
                rendered += " [main]"
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
    return 0 if result.succeeded else 1


def workspace_impact_command(argv: list[str]) -> int:
    args = _impact_parser().parse_args(argv)
    try:
        graph = discover(_existing_root(args.path))
        plan = plan_workspace_graph(graph, args.workspace)
    except (FileNotFoundError, NotADirectoryError, OSError, WorkspaceError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    result = execute_workspace_graph(plan)
    if not result.succeeded:
        if args.as_json:
            print(json.dumps({"module": args.module, "error": result.stderr, "returncode": result.returncode}, indent=2))
        else:
            print(f"x {plan.component}: {result.stderr}")
        return 1

    impacts = analyze_native_impact(result, args.module)
    if args.as_json:
        print(json.dumps({
            "module": args.module,
            "scope": "workspace-module-requirement",
            "workspace": plan.component,
            "impacts": [impact.to_dict() for impact in impacts],
        }, indent=2, sort_keys=True))
    else:
        print("Impact scope: workspace module requirement graph (not source/API impact)")
        for impact in impacts:
            rendered = f"{impact.module}"
            if impact.effective_name != impact.module:
                rendered += f" => {impact.effective_name}"
            if impact.selected_version:
                rendered += f" {impact.selected_version}"
            print(rendered)
            if impact.direct_dependents:
                print("  direct module dependents: " + ", ".join(impact.direct_dependents))
            if impact.transitive_dependents:
                print("  transitive module dependents: " + ", ".join(impact.transitive_dependents))
            for path in impact.root_paths:
                print("  root path: " + " -> ".join(path))
    return 0 if impacts else 1


def dispatch_workspace_command(arguments: list[str]) -> int | None:
    if not arguments:
        return None
    if arguments[0] == "workspaces":
        return list_workspaces_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "workspace":
        if arguments[1] == "inspect":
            return inspect_workspace_command(arguments[2:])
        if arguments[1] == "graph":
            return workspace_graph_command(arguments[2:])
        if arguments[1] == "impact":
            return workspace_impact_command(arguments[2:])
    return None
