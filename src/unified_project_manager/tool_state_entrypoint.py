from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .tool_inventory import collect_tool_inventory
from .tool_state import (
    DEFAULT_TOOL_STATE_PATH,
    ToolStateError,
    build_tool_state,
    compare_tool_state,
    load_tool_state,
    write_tool_state,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm tools-state",
        description="Preview/write or check the machine-local manager/toolchain resolution baseline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Preview or write the current local tool resolution baseline")
    snapshot.add_argument("path", nargs="?", default=".")
    snapshot.add_argument("--apply", action="store_true", help="Write .upm/tools.json; otherwise preview only")
    snapshot.add_argument("--json", action="store_true", dest="as_json")

    check = subparsers.add_parser("check", help="Compare current local tool resolution with the saved baseline")
    check.add_argument("path", nargs="?", default=".")
    check.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ToolStateError(f"Project root is not a directory: {root}")
    return root


def _quality(inventory) -> dict[str, int]:
    unavailable = sum(not item.available for item in inventory.resolutions)
    failed = sum(
        item.available and item.version_returncode not in (None, 0)
        for item in inventory.resolutions
    )
    return {
        "observations": len(inventory.resolutions),
        "unavailable": unavailable,
        "version_probe_failures": failed,
        "requirement_divergences": len(inventory.divergences),
    }


def tool_state_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _root(args.path)
        graph = discover(root)
        inventory = collect_tool_inventory(graph)
    except (OSError, ValueError, ToolStateError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        try:
            baseline = load_tool_state(root)
            status = compare_tool_state(baseline, inventory)
        except (OSError, ValueError, ToolStateError) as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2
        payload = {
            **status.to_dict(),
            "path": DEFAULT_TOOL_STATE_PATH.as_posix(),
            "quality": _quality(inventory),
            "network_executed": False,
            "mutation_executed": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif status.state == "current":
            print(f"Tool baseline: current ({status.current_state_id})")
        elif status.state == "absent":
            print("Tool baseline: absent. Preview one with 'tools-state snapshot'.")
        else:
            print("Tool baseline: drifted")
            for change in status.changes:
                print(
                    f"  {change.code:<27} {change.component} "
                    f"{change.role}:{change.name} {change.before!r} -> {change.after!r}"
                )
        return 0 if status.current else 1

    snapshot = build_tool_state(inventory)
    quality = _quality(inventory)
    if not args.apply:
        payload = {
            "executed": False,
            "snapshot": snapshot.to_dict(),
            "path": DEFAULT_TOOL_STATE_PATH.as_posix(),
            "quality": quality,
            "network_executed": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Tool observations: {len(snapshot.observations)}")
            print(f"Machine-local state ID: {snapshot.state_id}")
            print("Preview only. Re-run with --apply to write .upm/tools.json.")
            print("The baseline contains absolute executable paths and is intentionally non-portable.")
        return 0

    try:
        target = write_tool_state(root, snapshot)
    except (OSError, ValueError, ToolStateError) as exc:
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
        }, indent=2, sort_keys=True))
    else:
        print(str(target))
        print(f"Machine-local state ID: {snapshot.state_id}")
        print("This baseline is intentionally non-portable because it records absolute executable resolution.")
    return 0


def main(argv: list[str] | None = None) -> int:
    return tool_state_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
