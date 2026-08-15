from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .tool_resolution import collect_tool_resolution
from .tool_resolution_state import (
    DEFAULT_TOOL_RESOLUTION_STATE_PATH,
    ToolResolutionStateError,
    build_tool_resolution_state,
    compare_tool_resolution_state,
    load_tool_resolution_state,
    write_tool_resolution_state,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm tools-state",
        description="Preview/write or check an execution-mode-bound machine-local tool resolution baseline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Preview or write the current tool-resolution baseline")
    snapshot.add_argument("path", nargs="?", default=".")
    snapshot.add_argument("--apply", action="store_true", help="Write .upm/tools.json; otherwise preview only")
    snapshot.add_argument(
        "--probe-versions",
        action="store_true",
        help="Explicitly execute version probes and bind their results into the baseline",
    )
    snapshot.add_argument("--json", action="store_true", dest="as_json")

    check = subparsers.add_parser("check", help="Compare current resolution with the saved baseline")
    check.add_argument("path", nargs="?", default=".")
    check.add_argument(
        "--probe-versions",
        action="store_true",
        help="Explicitly allow version probes when (and only when) the saved baseline contains probe evidence",
    )
    check.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ToolResolutionStateError(f"Project root is not a directory: {root}")
    return root


def _quality(report) -> dict[str, int]:
    return {
        "observations": len(report.observations),
        "unavailable": sum(not item.available for item in report.observations),
        "version_probe_failures": sum(
            report.version_probes_executed
            and item.available
            and item.version_returncode not in (0,)
            for item in report.observations
        ),
        "requirement_divergences": len(report.divergences),
    }


def _execution_metadata(report) -> dict[str, object]:
    if report is None:
        return {
            "version_probes_executed": False,
            "network_guarantee": "no-execution",
            "network_executed": False,
        }
    return {
        "version_probes_executed": report.version_probes_executed,
        "network_guarantee": report.network_guarantee,
        "network_executed": False if not report.version_probes_executed else None,
    }


def tool_state_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _root(args.path)
        graph = discover(root)
    except (OSError, ValueError, ToolResolutionStateError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        try:
            baseline = load_tool_resolution_state(root)
        except (OSError, ValueError, ToolResolutionStateError) as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2

        if baseline is None:
            status = compare_tool_resolution_state(None, None)
            payload = {
                **status.to_dict(),
                "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
                **_execution_metadata(None),
                "mutation_executed": False,
            }
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("Tool resolution baseline: absent. Create one explicitly with 'tools-state snapshot'.")
            return 1

        if baseline.version_probes_executed and not args.probe_versions:
            status = compare_tool_resolution_state(baseline, None)
            payload = {
                **status.to_dict(),
                "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
                **_execution_metadata(None),
                "mutation_executed": False,
            }
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("Tool resolution baseline: probe-required")
                print(status.reason)
            return 1

        if not baseline.version_probes_executed and args.probe_versions:
            message = (
                "The saved baseline is path-only. Refusing to execute version probes for a mismatched check mode; "
                "re-snapshot explicitly with --probe-versions if version evidence is desired."
            )
            if args.as_json:
                print(json.dumps({"error": message}, indent=2))
            else:
                print(f"upm: {message}", file=sys.stderr)
            return 2

        try:
            report = collect_tool_resolution(
                graph,
                probe_versions=baseline.version_probes_executed,
            )
            status = compare_tool_resolution_state(baseline, report)
        except (OSError, ValueError) as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2
        payload = {
            **status.to_dict(),
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "quality": _quality(report),
            **_execution_metadata(report),
            "mutation_executed": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif status.current:
            print(f"Tool resolution baseline: current ({status.current_state_id})")
        else:
            print(f"Tool resolution baseline: {status.state}")
            for change in status.changes:
                print(
                    f"  {change.code:<27} {change.component} "
                    f"{change.role}:{change.name} {change.before!r} -> {change.after!r}"
                )
        return 0 if status.current else 1

    try:
        report = collect_tool_resolution(
            graph,
            probe_versions=args.probe_versions,
        )
        snapshot = build_tool_resolution_state(report)
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    quality = _quality(report)
    execution = _execution_metadata(report)
    if not args.apply:
        payload = {
            "executed": False,
            "snapshot": snapshot.to_dict(),
            "path": DEFAULT_TOOL_RESOLUTION_STATE_PATH.as_posix(),
            "quality": quality,
            **execution,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Tool observations: {len(snapshot.observations)}")
            print(f"Machine-local state ID: {snapshot.state_id}")
            print(f"Version probes bound: {'yes' if snapshot.version_probes_executed else 'no'}")
            if snapshot.version_probes_executed:
                print("Version probes executed local binaries/shims; universal offline behavior is not guaranteed.")
            else:
                print("No manager/toolchain executable was run.")
            print("Preview only. Re-run with --apply to write .upm/tools.json.")
        return 0

    try:
        target = write_tool_resolution_state(root, snapshot)
    except (OSError, ValueError, ToolResolutionStateError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps({
            "executed": True,
            "path": str(target),
            "snapshot": snapshot.to_dict(),
            "quality": quality,
            **execution,
        }, indent=2, sort_keys=True))
    else:
        print(str(target))
        print(f"Machine-local state ID: {snapshot.state_id}")
        print(f"Version probes bound: {'yes' if snapshot.version_probes_executed else 'no'}")
        print("The baseline is intentionally non-portable because it records absolute executable resolution.")
    return 0


def main(argv: list[str] | None = None) -> int:
    return tool_state_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
