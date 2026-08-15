from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .operations import OperationError, execute_plan, plan_operation
from .receipt_execution import execute_plans_with_receipt


def _parser(operation: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"upm {operation}",
        description=f"Preview or execute {operation} through the component's authoritative native manager",
    )
    if operation in {"add", "remove"}:
        parser.add_argument("packages", nargs="+")
    parser.add_argument("--path", default=".", help="Project root to discover")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or package name")
    parser.add_argument("--apply", action="store_true", help="Execute the native command; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-operation UPM doctor verification")
    if operation == "add":
        parser.add_argument("--dev", action="store_true", help="Add as a development dependency")
    return parser


def _verification_errors(verification: object) -> int:
    if not isinstance(verification, dict):
        return 0
    summary = verification.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get("errors")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def operation_command(operation: str, argv: list[str]) -> int:
    args = _parser(operation).parse_args(argv)
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
        plan = plan_operation(
            graph,
            operation,
            selector=args.component,
            packages=getattr(args, "packages", ()),
            dev=getattr(args, "dev", False),
        )
    except (FileNotFoundError, NotADirectoryError, OperationError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {"executed": False, "plan": plan.to_dict(root)}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            relative = plan.cwd.relative_to(root).as_posix() or "."
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Directory: {relative}")
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute the native command.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        operation,
        [plan],
        lambda selected: execute_plan(selected, root, verify=False),
        verify_after=None if args.no_verify else lambda after_graph: diagnose(after_graph),
    )
    result = execution.results[0] if execution.results else None
    verification = execution.receipt.verification

    if args.as_json:
        print(json.dumps({
            "executed": True,
            "result": result.to_dict(root) if result is not None else None,
            "verification": verification,
            "receipt": execution.receipt.to_dict(),
            "receipt_path": str(execution.receipt_path),
        }, indent=2, sort_keys=True))
    else:
        if result is not None:
            relative = plan.cwd.relative_to(root).as_posix() or "."
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Directory: {relative}")
            print(f"Command:   {shlex.join(plan.argv)}")
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
        if isinstance(verification, dict):
            summary = verification.get("summary", {})
            print(
                f"Post-operation health: {verification.get('health_score', '?')}% "
                f"({summary.get('errors', '?')} errors, {summary.get('warnings', '?')} warnings)"
            )
        try:
            receipt_text = execution.receipt_path.relative_to(root).as_posix()
        except ValueError:
            receipt_text = str(execution.receipt_path)
        print(f"Mutation receipt: {receipt_text}")

    if result is None:
        return 1
    returncode = getattr(result, "returncode", None)
    if returncode not in (None, 0):
        return returncode if isinstance(returncode, int) and 0 < returncode < 126 else 1
    if _verification_errors(verification):
        return 1
    return 0


def dispatch_operation_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] not in {"install", "sync", "add", "remove"}:
        return None
    if "--all" in arguments:
        return None
    return operation_command(arguments[0], arguments[1:])
