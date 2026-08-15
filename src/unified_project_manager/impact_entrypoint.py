from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .native_graph import NativeGraphError, execute_native_graph, plan_native_graph
from .native_impact import analyze_native_impact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm impact --native",
        description="Analyze reverse module-requirement impact from authoritative native graphs",
    )
    parser.add_argument("module")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native impact analysis to one component")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def impact_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project path is not a directory: {root}")
        graph = discover(root)
        plans, skips = plan_native_graph(graph, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeGraphError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    results = [execute_native_graph(plan) for plan in plans]
    failures = [result for result in results if not result.succeeded]
    impacts = []
    for result in results:
        if result.succeeded:
            impacts.extend(analyze_native_impact(result, args.module))

    if args.as_json:
        print(json.dumps({
            "module": args.module,
            "scope": "module-requirement",
            "impacts": [impact.to_dict() for impact in impacts],
            "failures": [
                {
                    "component": result.plan.component,
                    "returncode": result.returncode,
                    "error": result.stderr,
                }
                for result in failures
            ],
            "skips": [skip.to_dict() for skip in skips],
        }, indent=2, sort_keys=True))
    else:
        print("Impact scope: module requirement graph (not source/API impact)")
        for impact in impacts:
            rendered = f"{impact.component}: {impact.module}"
            if impact.effective_name != impact.module:
                rendered += f" => {impact.effective_name}"
            if impact.selected_version:
                rendered += f" {impact.selected_version}"
            print(rendered)
            if impact.direct_dependents:
                print("  direct module dependents: " + ", ".join(impact.direct_dependents))
            if impact.transitive_dependents:
                print("  transitive module dependents: " + ", ".join(impact.transitive_dependents))
            for path in impact.root_paths:
                print("  root path: " + " -> ".join(path))
        for failure in failures:
            print(f"x {failure.plan.component}: {failure.stderr}")
        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")

    if failures:
        return 1
    return 0 if impacts else 1


def dispatch_impact_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "impact" or "--native" not in arguments:
        return None
    return impact_command(arguments[1:])
