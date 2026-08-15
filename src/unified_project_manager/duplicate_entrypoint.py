from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .duplicate_classification import classify_duplicates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm duplicates",
        description="Classify normalized resolved duplicate observations without claiming physical reclaimability",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when duplicate observations exist")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def duplicates_command(argv: list[str]) -> int:
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
        report = classify_duplicates(discover(root))
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    data = report.to_dict()
    summary = {
        "observations": len(data["observations"]),
        "logical_repeats": sum(item["category"] == "logical-repeat" for item in data["observations"]),
        "version_divergences": sum(item["category"] == "version-divergence" for item in data["observations"]),
        "provenance_divergences": sum(item["category"] == "provenance-divergence" for item in data["observations"]),
        "strict_failed": bool(data["observations"]),
    }
    if args.as_json:
        print(json.dumps({
            **data,
            "summary": summary,
            "network_executed": False,
            "mutation_executed": False,
        }, indent=2, sort_keys=True))
    elif not data["observations"]:
        print("No normalized resolved duplicate observations found in covered components.")
    else:
        for item in data["observations"]:
            versions = ", ".join(item["versions"]) or "(unversioned)"
            print(f"{item['ecosystem']}:{item['name']} [{item['category']}] versions={versions}")
            for occurrence in item["occurrences"]:
                source = f" source={occurrence['source']}" if occurrence["source"] else ""
                location = f" location={occurrence['location']}" if occurrence["location"] else ""
                print(
                    f"  {occurrence['component']} {occurrence['version']}"
                    f"{source}{location}"
                )
            print("  reclaimable=false — " + item["rationale"])
        coverage = data["coverage"]
        print(
            "Resolved-inventory coverage: "
            f"{coverage['components_with_resolved_inventory']}/{coverage['total_components']} components"
        )
        print("Physical duplicate bytes were not analyzed by this command.")

    if args.strict and data["observations"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return duplicates_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
