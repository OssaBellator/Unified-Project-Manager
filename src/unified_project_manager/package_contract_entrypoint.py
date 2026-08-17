from __future__ import annotations

import argparse
import json
import sys

from .package_contract import PackageContractError, error_response, plan_package_operation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm package-plan",
        description="Emit one deterministic read-only package-operation provider plan",
    )
    parser.add_argument("operation", choices=("install", "sync", "add", "remove"))
    parser.add_argument("--root", default=".", help="Project root to inspect")
    parser.add_argument("--component", help="Exact or unambiguous UPM component selector")
    parser.add_argument("--package", dest="packages", action="append", default=[], help="Package specifier; repeat for multiple packages")
    parser.add_argument("--dev", action="store_true", help="Use the native manager's development dependency scope for add")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit the versioned provider envelope as JSON")
    return parser


def package_plan_command(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = plan_package_operation(
            args.root,
            args.operation,
            component=args.component,
            packages=args.packages,
            dev=args.dev,
        )
    except PackageContractError as exc:
        if args.as_json:
            print(json.dumps(error_response(exc), indent=2, sort_keys=True))
        else:
            print(f"upm: {exc.code}: {exc.message}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    else:
        execution = plan.execution_dict()
        print(f"Provider:  {plan.to_dict()['provider']['name']} {plan.to_dict()['provider']['version']}")
        print(f"Contract:  {plan.to_dict()['contract']['name']} {plan.to_dict()['contract']['version']}")
        print(f"Component: {execution['component']} ({execution['ecosystem']}/{execution['manager']})")
        print(f"Directory: {execution['cwd']}")
        print("Command:   " + " ".join(execution["argv"]))
        print("Planning only: no manager execution, project write, tool installation, or network access occurred.")
    return 0


def dispatch_package_contract_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "package-plan":
        return None
    return package_plan_command(arguments[1:])


if __name__ == "__main__":
    raise SystemExit(package_plan_command())
