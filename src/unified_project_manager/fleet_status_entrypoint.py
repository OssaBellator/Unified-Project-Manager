from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .discovery import discover
from .registry import RegistryError, registered_paths
from .status import project_status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm projects status",
        description="Summarize local evidence across explicitly registered projects",
    )
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--deep", action="store_true", help="Include installed-state doctor checks")
    parser.add_argument("--storage", action="store_true", help="Measure project-local artifact storage")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def fleet_status_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        roots = registered_paths(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    projects: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            projects.append({
                "path": str(root),
                "exists": False,
                "blocked": True,
                "blockers": ["project-missing"],
                "status": None,
            })
            continue
        try:
            status = project_status(
                discover(root),
                deep=args.deep,
                include_storage=args.storage,
            )
        except (OSError, ValueError) as exc:
            projects.append({
                "path": str(root),
                "exists": True,
                "blocked": True,
                "blockers": ["project-unreadable"],
                "error": str(exc),
                "status": None,
            })
            continue
        blockers = list(status["summary"].get("blockers", []))
        projects.append({
            "path": str(root),
            "exists": True,
            "blocked": bool(blockers),
            "blockers": blockers,
            "status": status,
        })

    blocked = sum(bool(item["blocked"]) for item in projects)
    missing = sum(not item["exists"] for item in projects)
    errors = sum("error" in item for item in projects)
    summary = {
        "projects": len(projects),
        "existing": len(projects) - missing,
        "missing": missing,
        "unreadable": errors,
        "blocked": blocked,
        "clear": len(projects) - blocked,
        "network_executed": False,
        "scanner_execution": False,
        "native_relationship_execution": False,
    }

    if args.as_json:
        print(json.dumps({"summary": summary, "projects": projects}, indent=2, sort_keys=True))
    elif not projects:
        print("No projects registered.")
    else:
        for item in projects:
            if not item["exists"]:
                print(f"x {item['path']}: missing")
                continue
            if item.get("error"):
                print(f"x {item['path']}: {item['error']}")
                continue
            status = item["status"]
            assert isinstance(status, dict)
            health = status["health"]
            advisory = status["advisory_evidence"]["state"]
            receipts = status["mutation_receipts"]["state"]
            marker = "x" if item["blocked"] else "✓"
            detail = ", ".join(item["blockers"]) if item["blockers"] else "clear"
            print(
                f"{marker} {item['path']}: health={health['health_score']}% "
                f"advisory={advisory} receipts={receipts} [{detail}]"
            )
        print(
            f"Fleet status: {summary['clear']}/{summary['projects']} clear; "
            f"{summary['blocked']} blocked"
        )
    return 1 if blocked else 0


def dispatch_fleet_status_command(arguments: list[str]) -> int | None:
    if len(arguments) < 2 or arguments[0] != "projects" or arguments[1] != "status":
        return None
    return fleet_status_command(arguments[2:])
