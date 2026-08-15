from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .workspace_ops import WorkspaceOperationError, execute_workspace_sync, prepare_workspace_sync


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm workspace sync",
        description="Synchronize a Go workspace build list back to member modules",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--workspace", help="Workspace key or relative path when multiple workspaces exist")
    parser.add_argument("--apply", action="store_true", help="Execute go work sync; otherwise preview affected state")
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow go work sync to modify workspace members outside the selected project root",
    )
    parser.add_argument("--no-verify", action="store_true", help="Skip post-sync UPM doctor verification")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def workspace_sync_command(argv: list[str]) -> int:
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
        plan = prepare_workspace_sync(graph, args.workspace)
    except (OSError, ValueError, WorkspaceOperationError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {
            "executed": False,
            "plan": plan.to_dict(root),
            "external_apply_blocked": bool(plan.external_members) and not args.allow_external,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Workspace: {plan.workspace}")
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Tracked files:")
            for path in plan.to_dict(root)["tracked_files"]:
                print(f"  {path}")
            if plan.external_members:
                print("External members:")
                for path in plan.external_members:
                    print(f"  {path}")
                if not args.allow_external:
                    print("Execution is blocked unless --allow-external is supplied.")
            print("Preview only. Re-run with --apply to execute workspace synchronization.")
        return 0

    try:
        result = execute_workspace_sync(plan, root, allow_external=args.allow_external)
    except WorkspaceOperationError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc), "plan": plan.to_dict(root)}, indent=2, sort_keys=True))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    verification = None
    if result.succeeded and not args.no_verify:
        verification = diagnose(discover(root))

    if args.as_json:
        payload = result.to_dict(root)
        payload["verification"] = verification.to_dict() if verification else None
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Workspace: {plan.workspace}")
        print(f"Command:   {shlex.join(plan.argv)}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.changed_files:
            print("Changed files:")
            for path in result.changed_files:
                print(f"  {path}")
        else:
            print("No tracked workspace/member files changed.")
        if verification:
            print(
                f"Post-sync health: {verification.health_score}% "
                f"({verification.errors} errors, {verification.warnings} warnings)"
            )

    if not result.succeeded:
        return result.returncode if result.returncode and 0 < result.returncode < 126 else 1
    return 1 if verification and verification.errors else 0


def dispatch_workspace_sync_command(arguments: list[str]) -> int | None:
    if len(arguments) >= 2 and arguments[0] == "workspace" and arguments[1] == "sync":
        return workspace_sync_command(arguments[2:])
    return None
