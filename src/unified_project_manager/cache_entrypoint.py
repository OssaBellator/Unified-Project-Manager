from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cache_integrity import plan_cache_verification, verify_go_module_cache
from .discovery import discover


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


def dispatch_cache_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "verify" or "--cache" not in arguments:
        return None
    return cache_verify_command(arguments[1:])
