from __future__ import annotations

import argparse
import json
import shlex
import sys

from .cache_maintenance import (
    CacheMaintenanceError,
    execute_cache_maintenance,
    plan_cache_clean,
    plan_cache_prune,
)


def _prune_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache prune",
        description="Preview or execute authoritative removal of unused/unreferenced shared-cache entries",
    )
    parser.add_argument("--manager", action="append", choices=("pnpm", "uv"), help="Limit pruning to one manager; repeatable")
    parser.add_argument("--apply", action="store_true", help="Execute native prune commands; otherwise preview them")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _clean_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm cache clean",
        description="Preview or execute full native cache removal",
    )
    parser.add_argument("--manager", required=True, choices=("npm", "go"))
    parser.add_argument("--category", choices=("build", "modules"), help="Required for Go: select build or downloaded module cache")
    parser.add_argument("--apply", action="store_true", help="Execute the full-cache removal; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _render_preview(plans: list[object], *, as_json: bool) -> int:
    payload = {
        "executed": False,
        "plans": [plan.to_dict() for plan in plans],
        "automatic": False,
        "derived_from_storage_measurement": False,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for plan in plans:
            print(f"{plan.manager}: {shlex.join(plan.argv)}")
            print(f"    Scope:  {plan.scope}")
            print(f"    Effect: {plan.effect}.")
            if plan.redownload_or_rebuild_possible:
                print("    Removed data may need to be downloaded or rebuilt again later.")
        print("Preview only. No cache maintenance is inferred from storage measurements; re-run with --apply to execute.")
    return 0 if plans else 1


def _execute(plans: list[object], *, as_json: bool) -> int:
    results = [execute_cache_maintenance(plan) for plan in plans]
    if as_json:
        print(json.dumps({
            "executed": True,
            "results": [result.to_dict() for result in results],
            "automatic": False,
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            symbol = "✓" if result.succeeded else "x"
            print(f"{symbol} {result.plan.manager}: {shlex.join(result.plan.argv)}")
            detail = (result.stdout or result.stderr).strip()
            if detail:
                print(f"    {detail}")
    return 0 if results and all(result.succeeded for result in results) else 1


def cache_prune_command(argv: list[str]) -> int:
    args = _prune_parser().parse_args(argv)
    managers = tuple(args.manager) if args.manager else ("pnpm", "uv")
    try:
        plans = plan_cache_prune(managers)
    except CacheMaintenanceError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    return _execute(plans, as_json=args.as_json) if args.apply else _render_preview(plans, as_json=args.as_json)


def cache_clean_command(argv: list[str]) -> int:
    args = _clean_parser().parse_args(argv)
    try:
        plan = plan_cache_clean(args.manager, go_category=args.category)
    except CacheMaintenanceError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    return _execute([plan], as_json=args.as_json) if args.apply else _render_preview([plan], as_json=args.as_json)


def dispatch_cache_maintenance_command(arguments: list[str]) -> int | None:
    if len(arguments) < 2 or arguments[0] != "cache":
        return None
    if arguments[1] == "prune":
        return cache_prune_command(arguments[2:])
    if arguments[1] == "clean":
        return cache_clean_command(arguments[2:])
    return None
