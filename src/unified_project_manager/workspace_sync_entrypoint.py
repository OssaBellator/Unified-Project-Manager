from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

from .discovery import discover
from .doctor import diagnose
from .receipt_execution import execute_plans_with_receipt
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


def _verification_errors(verification: object) -> int:
    if not isinstance(verification, dict):
        return 0
    summary = verification.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get("errors")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


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
            "receipt": None,
            "receipt_scope": (
                "project-complete" if not plan.external_members
                else "external-members-require-separate-change-report"
            ),
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
                print("External-member sync cannot be represented as a complete project-root mutation receipt.")
            else:
                print("Applied sync will persist a complete project-root mutation receipt.")
            print("Preview only. Re-run with --apply to execute workspace synchronization.")
        return 0

    # External-member writes are intentionally kept out of the project-root
    # receipt model. Creating a receipt for only the in-root subset would imply
    # completeness while omitting state that go work sync may also rewrite.
    if plan.external_members:
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
        verification_data = verification.to_dict() if verification else None
        receipt_reason = (
            "workspace contains explicitly allowed members outside the project root; "
            "project mutation receipts cannot truthfully capture the full external mutation scope"
        )

        if args.as_json:
            payload = result.to_dict(root)
            payload["verification"] = verification_data
            payload["receipt"] = None
            payload["receipt_path"] = None
            payload["receipt_scope"] = "external-unrepresented"
            payload["receipt_reason"] = receipt_reason
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
            print(f"Mutation receipt: not written ({receipt_reason}).")
            if verification:
                print(
                    f"Post-sync health: {verification.health_score}% "
                    f"({verification.errors} errors, {verification.warnings} warnings)"
                )

        if not result.succeeded:
            return result.returncode if result.returncode and 0 < result.returncode < 126 else 1
        return 1 if verification and verification.errors else 0

    receipt_plan = SimpleNamespace(
        component=plan.workspace,
        manager="go",
        cwd=plan.cwd,
        argv=plan.argv,
    )
    execution = execute_plans_with_receipt(
        graph,
        "workspace-sync",
        [receipt_plan],
        lambda _receipt_plan: execute_workspace_sync(plan, root, allow_external=False),
        extra_paths=plan.tracked_files,
        verify_after=None if args.no_verify else lambda after_graph: diagnose(after_graph),
    )
    result = execution.results[0] if execution.results else None
    verification_data = execution.receipt.verification

    if args.as_json:
        payload = result.to_dict(root) if result is not None else {
            "plan": plan.to_dict(root),
            "executed": False,
            "returncode": None,
            "succeeded": False,
            "changed_files": [],
            "stdout": "",
            "stderr": "",
        }
        payload["verification"] = verification_data
        payload["receipt"] = execution.receipt.to_dict()
        payload["receipt_path"] = str(execution.receipt_path)
        payload["receipt_scope"] = "project-complete"
        payload["receipt_reason"] = None
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Workspace: {plan.workspace}")
        print(f"Command:   {shlex.join(plan.argv)}")
        if result is not None:
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
        try:
            receipt_text = execution.receipt_path.relative_to(root).as_posix()
        except ValueError:
            receipt_text = str(execution.receipt_path)
        print(f"Mutation receipt: {receipt_text}")
        if isinstance(verification_data, dict):
            summary = verification_data.get("summary", {})
            print(
                f"Post-sync health: {verification_data.get('health_score', '?')}% "
                f"({summary.get('errors', '?')} errors, {summary.get('warnings', '?')} warnings)"
            )

    if result is None:
        return 1
    if not result.succeeded:
        return result.returncode if result.returncode and 0 < result.returncode < 126 else 1
    return 1 if _verification_errors(verification_data) else 0


def dispatch_workspace_sync_command(arguments: list[str]) -> int | None:
    if len(arguments) >= 2 and arguments[0] == "workspace" and arguments[1] == "sync":
        return workspace_sync_command(arguments[2:])
    return None
