from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .go_workspace import WorkspaceError, execute_workspace_inspection, plan_workspace_inspection


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


def dispatch_workspace_command(arguments: list[str]) -> int | None:
    if not arguments:
        return None
    if arguments[0] == "workspaces":
        return list_workspaces_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "workspace" and arguments[1] == "inspect":
        return inspect_workspace_command(arguments[2:])
    return None
