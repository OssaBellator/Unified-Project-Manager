from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .initializer import InitializationError, execute_initialization, plan_initialization
from .receipt_execution import execute_plans_with_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm init",
        description="Initialize a project through its native generator",
    )
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--ecosystem", required=True, choices=("node", "python", "rust", "go"))
    parser.add_argument("--manager", help="Native package manager/generator to delegate to")
    parser.add_argument("--lib", action="store_true", dest="library", help="Initialize a library where supported")
    parser.add_argument("--module", help="Go module path; required for --ecosystem go")
    parser.add_argument("--apply", action="store_true", help="Execute the native initializer; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-initialization UPM doctor verification")
    return parser


def _verification_errors(verification: object) -> int:
    if not isinstance(verification, dict):
        return 0
    summary = verification.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get("errors")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def init_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path.cwd().resolve()
    if args.module and args.ecosystem != "go":
        message = "--module is only valid with --ecosystem go."
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2
    try:
        graph = discover(root)
        plan = plan_initialization(
            root,
            args.target,
            args.ecosystem,
            args.manager,
            library=args.library,
            module=args.module,
        )
    except (FileNotFoundError, NotADirectoryError, InitializationError, ValueError) as exc:
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
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute this native initializer.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        "init",
        [plan],
        lambda selected: execute_initialization(selected, root, verify=False),
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


def dispatch_init_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "init":
        return None
    return init_command(arguments[1:])
