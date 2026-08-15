from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cache_integrity import plan_cache_verification, verify_go_module_cache
from .cache_provenance import collect_cache_provenance
from .discovery import discover
from .global_storage import global_cache_storage, global_storage_summary
from .registry import RegistryError
from .shared_cache_integrity import (
    execute_shared_cache_plan,
    plan_shared_cache_checks,
    plan_shared_cache_maintenance,
)


def _storage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache storage",
        description="Measure authoritative machine-wide package/build cache locations",
    )
    parser.add_argument(
        "--manager",
        action="append",
        choices=("go", "npm", "pnpm", "uv", "cargo"),
        help="Limit probing to one manager; repeatable",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _provenance_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache provenance",
        description=(
            "Attribute measured Go/Cargo cache bytes to explicitly registered projects "
            "using native physical package identity"
        ),
    )
    parser.add_argument(
        "--manager",
        action="append",
        choices=("go", "cargo"),
        help="Limit physical attribution to one supported manager; repeatable",
    )
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument(
        "--closed-universe",
        action="store_true",
        help=(
            "Assert that the registered project list is the complete relevant project universe; "
            "this never makes unattributed bytes reclaimable"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache check",
        description="Run documented non-mutating shared-cache integrity checks",
    )
    parser.add_argument("--manager", action="append", choices=("go", "npm", "pnpm", "uv", "cargo"), help="Limit checking to one manager; repeatable")
    parser.add_argument("--strict", action="store_true", help="Fail when a requested manager has no non-mutating cache check")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _maintenance_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache verify",
        description="Preview or run shared-cache verification that may perform maintenance",
    )
    parser.add_argument("--manager", action="append", choices=("npm",), help="Limit maintenance verification; repeatable")
    parser.add_argument("--apply", action="store_true", help="Execute cache verification/maintenance; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm verify --cache",
        description="Verify package-cache content using authoritative ecosystem checks",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit cache verification to one component")
    parser.add_argument("--strict", action="store_true", help="Fail when a component has no supported cache verifier")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--cache", action="store_true", help=argparse.SUPPRESS)
    return parser


def cache_verify_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {root}")
        graph = discover(root)
        components, skips = plan_cache_verification(graph, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    results = [verify_go_module_cache(component, graph.root) for component in components]
    if args.as_json:
        print(json.dumps({
            "scope": "package-cache-content",
            "results": [result.to_dict() for result in results],
            "skips": [skip.to_dict() for skip in skips],
            "notes": [
                "Go cache verification uses a temporary adjacent modfile so project go.mod/go.sum are not rewritten.",
                "The Go command may populate module metadata in the shared module cache while resolving the build list.",
            ],
        }, indent=2, sort_keys=True))
    else:
        print("Cache verification scope: downloaded package/module content")
        for result in results:
            symbol = "✓" if result.succeeded else "x"
            detail = (result.stdout or result.stderr).strip()
            print(f"{symbol} {result.component}: go mod verify")
            if detail:
                print(f"    {detail}")
        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")
        print("Note: Go may populate shared-cache module metadata; project go.mod/go.sum are isolated from writes.")

    if any(not result.succeeded for result in results):
        return 1
    if args.strict and skips:
        return 1
    return 0 if results else 1


def cache_storage_command(argv: list[str]) -> int:
    args = _storage_parser().parse_args(argv)
    managers = tuple(args.manager) if args.manager else ("go", "npm", "pnpm", "uv", "cargo")
    entries, skips = global_cache_storage(managers=managers)
    summary = global_storage_summary(entries)
    if args.as_json:
        print(json.dumps({
            "scope": "machine-wide-cache-storage",
            "summary": summary,
            "entries": [entry.to_dict() for entry in entries],
            "skips": [skip.to_dict() for skip in skips],
            "reclaimable": False,
        }, indent=2, sort_keys=True))
    else:
        if not entries:
            print("No supported machine-wide cache locations were measured.")
        for entry in entries:
            print(f"{entry.bytes / (1024 * 1024):9.2f} MiB  {entry.manager:<8} {entry.category:<13} {entry.path}")
        print(f"Total measured shared cache: {summary['bytes'] / (1024 * 1024):.2f} MiB")
        print("Measured bytes are not automatically reclaimable; no cleanup is performed.")
        for skip in skips:
            print(f"- {skip.manager}: skipped ({skip.reason})")
    return 0 if entries else 1


def cache_provenance_command(argv: list[str]) -> int:
    args = _provenance_parser().parse_args(argv)
    managers = tuple(args.manager) if args.manager else ("go", "cargo")
    try:
        report = collect_cache_provenance(
            args.registry,
            managers=managers,
            closed_universe=args.closed_universe,
        )
    except (RegistryError, OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        universe = report["project_universe"]
        state = "closed" if universe["closed"] else "open"
        if universe["closed_asserted"] and not universe["closed"]:
            state = "closure assertion invalidated by missing/unreadable registered projects"
        print(
            f"Registered project universe: {universe['observed']}/{universe['registered']} observed; {state}."
        )
        for manager in report["managers"]:
            total = manager["total_bytes"]
            attributed = manager["attributed_bytes"]
            unattributed = manager["unattributed_bytes"]
            ratio = manager["coverage_ratio"]
            rendered_ratio = "n/a" if ratio is None else f"{ratio * 100:.1f}%"
            print(
                f"{manager['manager']}: {attributed / (1024 * 1024):.2f} MiB attributed / "
                f"{total / (1024 * 1024):.2f} MiB measured ({rendered_ratio}); "
                f"{unattributed / (1024 * 1024):.2f} MiB unattributed."
            )
            if not manager["measurement_consistent"]:
                print("  x Attributed bytes exceed the measured cache total; observation is inconsistent.")
        for failure in report["provider_failures"]:
            print(
                f"x {failure['manager']} {failure['project']} "
                f"[{failure.get('component') or 'project'}]: {failure.get('error') or 'provider failed'}"
            )
        for skip in report["provider_skips"]:
            print(
                f"- {skip['manager']} {skip['project']} "
                f"[{skip.get('component') or 'project'}]: provider skipped ({skip.get('reason') or 'unsupported evidence'})."
            )
        for skip in report["attribution_skips"]:
            print(
                f"- {skip['manager']} {skip['project']} "
                f"[{skip.get('component') or 'project'}]: not cache-attributed ({skip.get('reason') or 'no physical cache identity'})."
            )
        for skip in report["storage_skips"]:
            print(f"- {skip['manager']}: storage skipped ({skip['reason']})")
        print("Unattributed bytes are not known unused, and this command makes no reclaim recommendation.")

    return 0 if report["observation_complete"] else 1


def cache_check_command(argv: list[str]) -> int:
    args = _check_parser().parse_args(argv)
    managers = tuple(args.manager) if args.manager else ("pnpm",)
    plans, skips = plan_shared_cache_checks(managers)
    results = [execute_shared_cache_plan(plan) for plan in plans]
    if args.as_json:
        print(json.dumps({
            "scope": "shared-cache-integrity",
            "mutates": False,
            "results": [result.to_dict() for result in results],
            "skips": [skip.to_dict() for skip in skips],
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            symbol = "✓" if result.succeeded else "x"
            print(f"{symbol} {result.plan.manager}: {' '.join(result.plan.argv)}")
            detail = (result.stdout or result.stderr).strip()
            if detail:
                print(f"    {detail}")
        for skip in skips:
            print(f"- {skip.manager}: skipped ({skip.reason})")
    if any(not result.succeeded for result in results):
        return 1
    if args.strict and skips:
        return 1
    return 0 if results else 1


def cache_maintenance_command(argv: list[str]) -> int:
    args = _maintenance_parser().parse_args(argv)
    managers = tuple(args.manager) if args.manager else ("npm",)
    plans, skips = plan_shared_cache_maintenance(managers)
    if not args.apply:
        if args.as_json:
            print(json.dumps({
                "scope": "shared-cache-maintenance-verification",
                "executed": False,
                "plans": [plan.to_dict() for plan in plans],
                "skips": [skip.to_dict() for skip in skips],
            }, indent=2, sort_keys=True))
        else:
            for plan in plans:
                print(f"{plan.manager}: {' '.join(plan.argv)}")
                print(f"    Side effect: {plan.effect}.")
            for skip in skips:
                print(f"- {skip.manager}: skipped ({skip.reason})")
            print("Preview only. Re-run with --apply to execute shared-cache maintenance verification.")
        return 0 if plans else 1

    results = [execute_shared_cache_plan(plan) for plan in plans]
    if args.as_json:
        print(json.dumps({
            "scope": "shared-cache-maintenance-verification",
            "executed": True,
            "results": [result.to_dict() for result in results],
            "skips": [skip.to_dict() for skip in skips],
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            symbol = "✓" if result.succeeded else "x"
            print(f"{symbol} {result.plan.manager}: {' '.join(result.plan.argv)}")
            detail = (result.stdout or result.stderr).strip()
            if detail:
                print(f"    {detail}")
    return 0 if results and all(result.succeeded for result in results) else 1


def dispatch_cache_command(arguments: list[str]) -> int | None:
    if not arguments:
        return None
    if arguments[0] == "verify" and "--cache" in arguments:
        return cache_verify_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "cache" and arguments[1] == "storage":
        return cache_storage_command(arguments[2:])
    if len(arguments) >= 2 and arguments[0] == "cache" and arguments[1] == "provenance":
        return cache_provenance_command(arguments[2:])
    if len(arguments) >= 2 and arguments[0] == "cache" and arguments[1] == "check":
        return cache_check_command(arguments[2:])
    if len(arguments) >= 2 and arguments[0] == "cache" and arguments[1] == "verify":
        return cache_maintenance_command(arguments[2:])
    if len(arguments) >= 2 and arguments[0] == "cache" and arguments[1] in {"prune", "clean"}:
        from .cache_maintenance_entrypoint import dispatch_cache_maintenance_command

        return dispatch_cache_maintenance_command(arguments)
    return None
