from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .tool_resolution import collect_tool_resolution


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm tools",
        description="Inspect exact local manager/toolchain resolution; version execution is explicit opt-in",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument(
        "--probe-versions",
        action="store_true",
        help=(
            "Execute local version commands. Corepack networking is disabled as a mitigation, "
            "but arbitrary shims may have their own behavior; offline execution is not guaranteed."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero for unavailable tools, requirement divergence, or failed probes when probes were requested",
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
        report = collect_tool_resolution(
            discover(root),
            probe_versions=args.probe_versions,
        )
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    data = report.to_dict()
    unavailable = [item for item in data["observations"] if not item["available"]]
    failed_probes = [
        item for item in data["observations"]
        if args.probe_versions and item["available"] and item["version_returncode"] not in (0,)
    ]
    summary = {
        "observations": len(data["observations"]),
        "unavailable": len(unavailable),
        "version_probe_failures": len(failed_probes),
        "requirement_divergences": len(data["divergences"]),
        "version_probes_executed": args.probe_versions,
        "strict_failed": bool(unavailable or failed_probes or data["divergences"]),
    }
    payload = {
        **data,
        "summary": summary,
        "probe_warning": (
            "Version probes executed local resolved binaries/shims; universal offline behavior cannot be guaranteed."
            if args.probe_versions
            else None
        ),
    }

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not data["observations"]:
        print("No supported manager/toolchain resolutions were discovered.")
    else:
        for item in data["observations"]:
            if not item["available"]:
                version = "unavailable"
            elif not args.probe_versions:
                version = "version-not-probed"
            elif item["version_returncode"] != 0:
                version = f"probe-failed/{item['version_returncode']}"
            else:
                version = item["version"] or "version-unreported"
            requirement = f" required={item['requirement']}" if item["requirement"] else ""
            print(
                f"{item['component']} {item['role']}:{item['name']} {version} "
                f"[{item['resolved_path'] or '(not found)'}]{requirement}"
            )
        for divergence in data["divergences"]:
            print(
                f"! divergent {divergence['role']}:{divergence['name']} requirements: "
                + ", ".join(divergence["requirements"])
            )
        if args.probe_versions:
            print("Version probes executed local binaries/shims; Corepack networking was disabled, but universal offline behavior is not guaranteed.")
        else:
            print("No manager/toolchain executable was run. Use --probe-versions to opt into version execution.")

    if args.strict and summary["strict_failed"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return tools_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
