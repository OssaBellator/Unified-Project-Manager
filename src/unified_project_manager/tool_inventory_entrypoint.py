from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .tool_inventory import collect_tool_inventory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm tools",
        description="Show exact local manager/toolchain resolution and version observations",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero for unavailable tools, failed version probes, or divergent declared requirements",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def tools_command(argv: list[str]) -> int:
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
        inventory = collect_tool_inventory(discover(root))
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    data = inventory.to_dict()
    unavailable = [item for item in data["resolutions"] if not item["available"]]
    probe_failures = [
        item
        for item in data["resolutions"]
        if item["available"] and item["version_returncode"] not in (None, 0)
    ]
    summary = {
        "observations": len(data["resolutions"]),
        "unavailable": len(unavailable),
        "version_probe_failures": len(probe_failures),
        "requirement_divergences": len(data["divergences"]),
        "strict_failed": bool(unavailable or probe_failures or data["divergences"]),
    }

    if args.as_json:
        print(json.dumps({**data, "summary": summary}, indent=2, sort_keys=True))
    elif not data["resolutions"]:
        print("No supported manager/toolchain version probes were discovered.")
    else:
        for item in data["resolutions"]:
            if not item["available"]:
                rendered = "unavailable"
            elif item["version_returncode"] not in (None, 0):
                rendered = f"probe-failed/{item['version_returncode']}"
            else:
                rendered = item["version"] or "version-unreported"
            requirement = f" required={item['requirement']}" if item["requirement"] else ""
            path = item["resolved_path"] or "(not found)"
            print(
                f"{item['component']} {item['role']}:{item['name']} "
                f"{rendered} [{path}]{requirement}"
            )
        for divergence in data["divergences"]:
            print(
                f"! divergent {divergence['role']}:{divergence['name']} requirements: "
                + ", ".join(divergence["requirements"])
            )
        print("Tool inventory is local-only; no installs, updates, or network probes are performed.")

    if args.strict and summary["strict_failed"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return tools_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
