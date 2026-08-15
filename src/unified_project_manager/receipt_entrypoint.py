from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .receipt_history import receipt_history_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm receipts",
        description="Inspect persisted local mutation-receipt history and current-state drift",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def receipts_command(argv: list[str]) -> int:
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
        status = receipt_history_status(discover(root))
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    validations = status.get("validations", [])
    invalid = [item for item in validations if not item.get("valid")]
    drifted = status.get("state") == "drifted"

    if args.as_json:
        print(json.dumps({
            **status,
            "invalid_receipts": len(invalid),
            "current_state_drift": drifted,
            "network_executed": False,
            "mutation_executed": False,
        }, indent=2, sort_keys=True))
    elif not validations:
        print("No mutation receipts recorded for this project.")
    else:
        print(f"Receipt history: {len(validations)} receipt(s); state={status.get('state')}")
        for item in validations:
            marker = "✓" if item.get("valid") else "x"
            operation = item.get("operation") or "unknown"
            returncode = item.get("returncode")
            result = "success" if item.get("succeeded") else f"failed/{returncode}"
            print(f"{marker} {item.get('receipt_id')}  {operation}  {result}")
            for issue in item.get("issues", []):
                print(f"    {issue}")
        if drifted:
            print("Current native project state differs from the latest recorded post-mutation state:")
            for change in status.get("changes", []):
                print(f"  {change['status']:<9} {change['path']}")
        elif status.get("state") == "current":
            print("Current native project state matches the latest receipt baseline.")

    return 1 if invalid or drifted else 0


def dispatch_receipt_command(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] != "receipts":
        return None
    return receipts_command(arguments[1:])
