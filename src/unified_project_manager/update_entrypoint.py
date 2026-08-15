from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .native_exec import execute_native_exec
from .receipt_execution import execute_plans_with_receipt
from .update_operation import UpdateOperationError, plan_update


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm update",
        description="Preview or execute a manager-native dependency update without replacing native resolution semantics",
    )
    parser.add_argument("packages", nargs="*", help="Optional manager-native package/module targets")
    parser.add_argument("--path", default=".", help="Project root to discover")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or project/package name")
    parser.add_argument("--apply", action="store_true", help="Execute the native update; otherwise preview it")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-update doctor verification")
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


def update_command(argv: list[str]) -> int:
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
        plan = plan_update(graph, selector=args.component, packages=args.packages)
    except (OSError, ValueError, UpdateOperationError) as exc:
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
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Command:   {shlex.join(plan.argv)}")
            print(f"Semantics: {plan.semantics}")
            print(
                "Potential effects: "
                f"manifest={'yes' if plan.manifest_may_change else 'no'}, "
                f"native-state={'yes' if plan.native_state_may_change else 'no'}, "
                f"installed-state={'yes' if plan.installed_state_may_change else 'no'}, "
                f"network={'yes' if plan.network_may_be_used else 'no'}"
            )
            print("Preview only. Re-run with --apply to execute the native update and persist a mutation receipt.")
        return 0

    execution = execute_plans_with_receipt(
        graph,
        "update",
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

    if result is None:
        return 1
    if result.returncode != 0:
        return result.returncode if 0 < result.returncode < 126 else 1
    return 1 if _verification_errors(verification) else 0


def main(argv: list[str] | None = None) -> int:
    return update_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
