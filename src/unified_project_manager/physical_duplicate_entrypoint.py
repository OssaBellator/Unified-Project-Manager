from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import discover
from .physical_duplicate_scan import analyze_physical_duplicates


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm duplicates-physical",
        description="Hash known project-local artifact roots and report repeated content on distinct physical file identities",
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument(
        "--min-size-bytes",
        type=int,
        default=4096,
        help="Ignore regular files smaller than this threshold before hashing (default: 4096)",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when repeated physical content groups are observed")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def physical_duplicates_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        message = f"project path is not a directory: {root}"
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2
    if args.min_size_bytes < 0:
        message = "--min-size-bytes must be non-negative."
        if args.as_json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(f"upm: {message}", file=sys.stderr)
        return 2

    try:
        report = analyze_physical_duplicates(
            discover(root),
            min_size_bytes=args.min_size_bytes,
        )
    except (OSError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    data = report.to_dict()
    if args.as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        summary = data["summary"]
        print(
            f"Scanned {summary['files_considered']} path(s) representing "
            f"{summary['physical_files_considered']} physical file identity/identities; "
            f"hashed {summary['bytes_hashed']} bytes."
        )
        print(f"Minimum file size: {summary['min_size_bytes']} bytes")
        if not data["groups"]:
            print("No repeated content was observed on distinct physical file identities.")
        for group in data["groups"]:
            print(
                f"sha256:{group['sha256']} size={group['size']} "
                f"instances={len(group['physical_instances'])} "
                f"duplicate-content-bytes={group['duplicate_content_bytes']}"
            )
            for instance in group["physical_instances"]:
                print("  physical instance: " + ", ".join(instance["paths"]))
            print("  reclaimable=false")
        for hardlink in data["hardlinks"]:
            print(
                f"hardlink-shared size={hardlink['size']} paths="
                + ", ".join(hardlink["paths"])
            )
            print("  duplicate-content-bytes=0 (same physical inode)")
        if data["skipped"]:
            print(f"Skipped {len(data['skipped'])} path(s)/root(s); see JSON output for details.")
        print(
            f"Observed repeated-content bytes: {summary['duplicate_content_bytes']}; "
            "this is not an automatic reclaimable-byte estimate."
        )
        print("No files were deleted, linked, or rewritten.")

    if args.strict and report.groups:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return physical_duplicates_command(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
