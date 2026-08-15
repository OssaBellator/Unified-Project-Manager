from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .advisory_v2_status import evaluate_advisory_v2_status
from .discovery import discover


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm advisory-v2-status",
        description="Evaluate persisted advisory evidence v2 without running scanners or native providers",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--max-age-seconds", type=int, help="Treat older evidence as expired")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def status_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        message = f"project path is not a directory: {root}"
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2
    if args.max_age_seconds is not None and args.max_age_seconds < 0:
        message = "--max-age-seconds must be non-negative."
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2

    try:
        graph = discover(root)
        status = evaluate_advisory_v2_status(
            graph,
            max_age_seconds=args.max_age_seconds,
        )
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    payload = {
        **status.to_dict(),
        "network_executed": False,
        "scanner_execution": False,
        "native_provider_execution": False,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Advisory evidence v2: {status.state}")
        if status.vulnerabilities is not None:
            print(
                f"Findings: {status.vulnerabilities} vulnerability ID(s) "
                f"across {status.affected_packages} affected package occurrence(s)"
            )
        if status.age_seconds is not None:
            print(f"Evidence age: {status.age_seconds} seconds")
        if status.reason:
            print(status.reason)

    if status.state == "current-clean":
        return 0
    if status.state == "current-vulnerable":
        return 1
    if status.state == "absent":
        return 1
    return 2 if status.state == "invalid" else 1


def main(argv: list[str] | None = None) -> int:
    return status_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
