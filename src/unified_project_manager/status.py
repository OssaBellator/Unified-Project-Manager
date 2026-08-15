from __future__ import annotations

from pathlib import Path
from typing import Any

from .cache_coverage import cache_integrity_coverage
from .doctor import diagnose
from .models import ProjectGraph
from .policy import evaluate_policy
from .storage import project_storage, storage_summary
from .verifier import plan_native_verification

SNAPSHOT_PATH = Path(".upm/state.json")


def project_status(
    graph: ProjectGraph,
    *,
    deep: bool = False,
    include_storage: bool = False,
) -> dict[str, Any]:
    report = diagnose(graph, deep=deep)
    policy = evaluate_policy(graph, deep=deep)
    verification_plans, verification_skips = plan_native_verification(graph)
    components = [component.to_dict(graph.root) for component in graph.components]
    workspaces = [workspace.to_dict(graph.root) for workspace in graph.workspaces]
    result: dict[str, Any] = {
        "root": str(graph.root),
        "components": components,
        "workspaces": workspaces,
        "summary": {
            "components": len(graph.components),
            "workspaces": len(graph.workspaces),
            "ecosystems": sorted({component.ecosystem for component in graph.components}),
            "workspace_ecosystems": sorted({workspace.ecosystem for workspace in graph.workspaces}),
            "managers": sorted({component.manager for component in graph.components if component.manager}),
            "direct_dependencies": sum(len(component.dependencies) for component in graph.components),
            "resolved_packages": sum(len(component.resolved_packages) for component in graph.components),
        },
        "health": report.to_dict(),
        "policy": policy.to_dict(),
        "integrity_snapshot": {
            "path": SNAPSHOT_PATH.as_posix(),
            "exists": (graph.root / SNAPSHOT_PATH).is_file(),
        },
        "native_verification": {
            "planned": [plan.to_dict(graph.root) for plan in verification_plans],
            "skipped": [skip.to_dict() for skip in verification_skips],
            "coverage": {
                "planned_components": len(verification_plans),
                "skipped_components": len(verification_skips),
                "total_components": len(graph.components),
            },
        },
        "cache_integrity": {
            "coverage": [item.to_dict() for item in cache_integrity_coverage(graph)],
        },
    }
    if include_storage:
        entries = project_storage(graph)
        result["storage"] = {
            "summary": storage_summary(entries),
            "entries": entries,
        }
    else:
        result["storage"] = None
    return result
