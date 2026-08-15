from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .batch_operations import plan_all_operations
from .discovery import discover
from .doctor import diagnose
from .operations import execute_plan
from .pnpm_workspace import PnpmWorkspaceResult, execute_pnpm_workspace
from .workspace_batch import (
    WorkspaceBatchError,
    WorkspaceInspectionRequired,
    required_pnpm_workspace_inspections,
)


def _parser(operation: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"upm {operation} --all",
        description="Plan or execute a workspace-aware operation across all discovered components",
    )
    parser.add_argument("--path", default=".", help="Project root to discover")
    parser.add_argument("--component", help=argparse.SUPPRESS)
    parser.add_argument("--all", action="store_true", dest="all_components", help=argparse.SUPPRESS)
    parser.add_argument("--apply", action="store_true", help="Execute the native commands; otherwise preview them")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-operation UPM doctor verification")
    return parser


def _inspect_pnpm_workspaces(graph, roots: tuple[Path, ...]) -> list[PnpmWorkspaceResult]:
    required = {
        plan.root.resolve(): plan
        for plan in required_pnpm_workspace_inspections(graph)
    }
    results: list[PnpmWorkspaceResult] = []
    for root in roots:
        plan = required.get(root.resolve())
        if plan is None:
            raise WorkspaceBatchError(f"No pnpm workspace inspection plan exists for {root}.")
        result = execute_pnpm_workspace(plan)
        if not result.succeeded:
            detail = result.stderr.strip() or result.stdout.strip() or f"pnpm exited with {result.returncode}"
            raise WorkspaceBatchError(f"pnpm workspace inspection failed for {root}: {detail}")
        results.append(result)
    return results


def _plan(graph, operation: str) -> tuple[list, object, list[PnpmWorkspaceResult]]:
    inspections: list[PnpmWorkspaceResult] = []
    try:
        plans, batch = plan_all_operations(graph, operation)
    except WorkspaceInspectionRequired as required:
        inspections = _inspect_pnpm_workspaces(graph, required.roots)
        plans, batch = plan_all_operations(graph, operation, pnpm_results=inspections)
    return plans, batch, inspections


def batch_operation_command(operation: str, argv: list[str]) -> int:
    args = _parser(operation).parse_args(argv)
    if args.component:
        message = "--all cannot be combined with --component."
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2

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
        plans, batch, inspections = _plan(graph, operation)
    except (OSError, ValueError, WorkspaceBatchError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    inspection_rows = [result.to_dict() for result in inspections]
    if not args.apply:
        payload = {
            "executed": False,
            "plans": [plan.to_dict(root) for plan in plans],
            "workspace_batch": batch.to_dict(root),
            "workspace_inspections": inspection_rows,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for result in inspections:
                print(f"Inspected pnpm workspace: {result.plan.root} (non-mutating, no network)")
            for plan in plans:
                relative = plan.cwd.relative_to(root).as_posix() or "."
                print(f"{plan.component}: ({relative}) {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute the workspace-aware batch plan.")
        return 0

    results = []
    for plan in plans:
        result = execute_plan(plan, root, verify=False)
        results.append(result)
        if result.returncode not in (None, 0):
            break

    verification = None
    if (
        len(results) == len(plans)
        and all(result.returncode == 0 for result in results)
        and not args.no_verify
    ):
        verification = diagnose(discover(root))

    if args.as_json:
        print(json.dumps({
            "executed": True,
            "results": [result.to_dict(root) for result in results],
            "workspace_batch": batch.to_dict(root),
            "workspace_inspections": inspection_rows,
            "verification": verification.to_dict() if verification else None,
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            relative = result.plan.cwd.relative_to(root).as_posix() or "."
            print(f"{result.plan.component}: ({relative}) {shlex.join(result.plan.argv)}")
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if verification:
            print(
                f"Post-operation health: {verification.health_score}% "
                f"({verification.errors} errors, {verification.warnings} warnings)"
            )

    failed = next((result for result in results if result.returncode not in (None, 0)), None)
    if failed:
        return failed.returncode if failed.returncode and 0 < failed.returncode < 126 else 1
    if len(results) != len(plans):
        return 1
    if verification and verification.errors:
        return 1
    return 0


def dispatch_batch_operation_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] not in {"install", "sync"} or "--all" not in arguments:
        return None
    return batch_operation_command(arguments[0], arguments[1:])
