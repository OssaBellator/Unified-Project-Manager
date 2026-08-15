from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .environment_inspection import inspect_environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm env",
        description="Inspect known path-like environment variables for project leakage without dumping arbitrary environment data",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when leakage warnings are present")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def environment_command(argv: list[str]) -> int:
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
        inspection = inspect_environment(discover(root))
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    data = inspection.to_dict()
    warnings = [item for item in data["findings"] if item["severity"] == "warning"]
    summary = {
        "observations": len(data["observations"]),
        "warnings": len(warnings),
        "strict_failed": bool(warnings),
    }
    if args.as_json:
        print(json.dumps({**data, "summary": summary}, indent=2, sort_keys=True))
    elif not data["observations"]:
        print("No relevant environment overrides were observed for the discovered ecosystems.")
    else:
        for item in data["observations"]:
            location = item["path"] if item["path"] is not None else item["value"]
            if item["in_project"] is True:
                scope = "project"
            elif item["in_project"] is False:
                scope = "external/shared"
            else:
                scope = "mode"
            print(f"{item['variable']:<18} {item['kind']:<20} {scope:<15} {location}")
        for finding in data["findings"]:
            print(f"! {finding['code']}: {finding['message']}")
        print("Only known path-like environment variables are inspected; arbitrary environment values are not emitted.")

    if args.strict and warnings:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return environment_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
