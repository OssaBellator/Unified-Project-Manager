from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .native_exec import NativeExecError, execute_native_exec, plan_native_exec
from .receipt_execution import execute_plans_with_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm exec",
        description="Preview or execute arbitrary argv through a component's authoritative native manager",
    )
    parser.add_argument("--path", default=".", help="Project root to discover")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or package name")
    parser.add_argument("--apply", action="store_true", help="Execute the command; otherwise preview it")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-command UPM doctor verification")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments passed to the authoritative native manager")
    return parser


def _verification_errors(verification: object) -> int:
    if not isinstance(verification, dict):
        return 0
    summary = verification.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get("errors")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def exec_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    manager_args = list(args.arguments)
    if manager_args and manager_args[0] == "--":
        manager_args = manager_args[1:]
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
        plan = plan_native_exec(graph, manager_args, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeExecError, ValueError) as exc:
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
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Directory: {plan.to_dict(root)['cwd']}")
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute through the native manager.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        "exec",
        [plan],
        lambda selected: execute_native_exec(selected, root, verify=False),
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
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Command:   {shlex.join(plan.argv)}")
            stdout = getattr(result, "stdout", "") or ""
            stderr = getattr(result, "stderr", "") or ""
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
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


def dispatch_exec_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "exec":
        return None
    return exec_command(arguments[1:])
