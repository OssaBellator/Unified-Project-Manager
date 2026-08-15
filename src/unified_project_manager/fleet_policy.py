from __future__ import annotations

from pathlib import Path
from typing import Any

from .discovery import discover
from .policy import PolicyError, evaluate_policy
from .registry import registered_paths


def registered_policy_statuses(
    registry: str | Path | None = None,
    *,
    deep: bool = False,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for root in registered_paths(registry):
        if not root.is_dir():
            statuses.append({
                "path": str(root),
                "exists": False,
                "passed": False,
                "error": "registered project root is missing",
                "report": None,
            })
            continue
        try:
            report = evaluate_policy(discover(root), deep=deep)
        except (OSError, ValueError, PolicyError) as exc:
            statuses.append({
                "path": str(root),
                "exists": True,
                "passed": False,
                "error": str(exc),
                "report": None,
            })
            continue
        statuses.append({
            "path": str(root),
            "exists": True,
            "passed": report.passed,
            "error": None,
            "report": report.to_dict(),
        })
    return statuses


def fleet_policy_summary(statuses: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "projects": len(statuses),
        "passed": sum(bool(item.get("passed")) for item in statuses),
        "failed": sum(not bool(item.get("passed")) for item in statuses),
        "missing": sum(not bool(item.get("exists")) for item in statuses),
        "errors": sum(bool(item.get("error")) for item in statuses),
    }
