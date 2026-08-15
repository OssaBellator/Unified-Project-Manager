from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .dedupe_operation import DedupeOperationError, plan_dedupe
from .discovery import discover
from .doctor import diagnose
from .native_exec import execute_native_exec
from .receipt_execution import execute_plans_with_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm dedupe",
        description="Preview or execute a first-party native project dedupe where the authoritative manager supports it",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or project/package name")
    parser.add_argument("--apply", action="store_true", help="Execute native dedupe; otherwise preview it")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-dedupe doctor verification")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _verification_errors(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    summary = value.get("summary")
    if not isinstance(summary, dict):
        return 0
    errors = summary.get("errors")
    return errors if isinstance(errors, int) and not isinstance(errors, bool) else 0


def dedupe_command(argv: list[str]) -> int:
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
        plan = plan_dedupe(graph, selector=args.component)
    except (OSError, ValueError, DedupeOperationError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        payload = {
            "executed": False,
            "plan": plan.to_dict(root),
            "receipt_will_be_written": True,
            "receipt_scope": "project-native-state",
            "receipt_limit": (
                "installed-tree changes may occur outside the manifest/lock-state bytes captured by the project-native-state receipt"
            ),
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Command:   {shlex.join(plan.argv)}")
            print(f"Semantics: {plan.semantics}")
            print("Receipt scope: project-native-state; installed-tree rearrangement is not a full filesystem transaction log.")
            print("Preview only. Re-run with --apply to execute native dedupe and persist a mutation receipt.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        "dedupe",
        [plan],
        lambda selected: execute_native_exec(selected.native, root, verify=False),
        verify_after=None if args.no_verify else lambda after_graph: diagnose(after_graph),
    )
    result = execution.results[0] if execution.results else None
    verification = execution.receipt.verification

    if args.as_json:
        print(json.dumps({
            "executed": True,
            "plan": plan.to_dict(root),
            "result": result.to_dict(root) if result is not None else None,
            "verification": verification,
            "receipt": execution.receipt.to_dict(),
            "receipt_path": str(execution.receipt_path),
            "receipt_limit": (
                "installed-tree changes may occur outside the manifest/lock-state bytes captured by the project-native-state receipt"
            ),
        }, indent=2, sort_keys=True))
    else:
        print(f"Component: {plan.component} ({plan.manager})")
        print(f"Command:   {shlex.join(plan.argv)}")
        if result is not None:
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        try:
            receipt_path = execution.receipt_path.relative_to(root).as_posix()
        except ValueError:
            receipt_path = str(execution.receipt_path)
        print(f"Mutation receipt: {receipt_path}")
        print("Receipt scope is project-native-state; installed-tree changes may not appear as receipt file diffs.")

    if result is None:
        return 1
    if result.returncode != 0:
        return result.returncode if 0 < result.returncode < 126 else 1
    return 1 if _verification_errors(verification) else 0


def main(argv: list[str] | None = None) -> int:
    return dedupe_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
