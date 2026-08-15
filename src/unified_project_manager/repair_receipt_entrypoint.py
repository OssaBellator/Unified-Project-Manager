from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .operations import execute_plan
from .receipt_execution import execute_plans_with_receipt
from .repair import RepairError, plan_repairs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm repair",
        description="Plan safe native repairs for detected installed-state drift",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit repair planning to one component")
    parser.add_argument("--apply", action="store_true", help="Execute the repair plan; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-repair deep doctor verification")
    return parser


def _verification_errors(verification: object) -> int:
    if not isinstance(verification, dict):
        return 0
    summary = verification.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get("errors")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def repair_command(argv: list[str]) -> int:
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
        deep_report = diagnose(graph, deep=True)
        plans = plan_repairs(graph, deep_report, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, RepairError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not plans:
        data = {"executed": False, "plans": [], "diagnosis": deep_report.to_dict()}
        if args.as_json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            print("No safely repairable installed-state drift detected.")
            if deep_report.errors:
                print("The project still has non-repairable errors; review 'upm doctor --deep'.")
        return 1 if deep_report.errors else 0

    if not args.apply:
        payload = {
            "executed": False,
            "plans": [plan.to_dict(root) for plan in plans],
            "diagnosis": deep_report.to_dict(),
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for plan in plans:
                relative = plan.cwd.relative_to(root).as_posix() or "."
                print(f"{plan.component}: ({relative}) {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute the repair plan.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        "repair",
        plans,
        lambda plan: execute_plan(plan, root, verify=False),
        verify_after=None if args.no_verify else lambda after_graph: diagnose(after_graph, deep=True),
    )
    results = list(execution.results)
    verification = execution.receipt.verification

    if args.as_json:
        print(json.dumps({
            "executed": True,
            "results": [result.to_dict(root) for result in results],
            "verification": verification,
            "diagnosis": deep_report.to_dict(),
            "receipt": execution.receipt.to_dict(),
            "receipt_path": str(execution.receipt_path),
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            relative = result.plan.cwd.relative_to(root).as_posix() or "."
            print(f"{result.plan.component}: ({relative}) {shlex.join(result.plan.argv)}")
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        try:
            receipt_text = execution.receipt_path.relative_to(root).as_posix()
        except ValueError:
            receipt_text = str(execution.receipt_path)
        print(f"Mutation receipt: {receipt_text}")

    failed = next((result for result in results if result.returncode not in (None, 0)), None)
    if failed:
        return failed.returncode if failed.returncode and 0 < failed.returncode < 126 else 1
    if len(results) != len(plans):
        return 1
    if _verification_errors(verification):
        return 1
    return 0


def dispatch_repair_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "repair":
        return None
    return repair_command(arguments[1:])
