from __future__ import annotations

from .models import Finding, ProjectGraph
from .uv_workspace import UvWorkspaceError, inspect_uv_workspace, uv_workspace_ownership


def uv_workspace_findings(graph: ProjectGraph) -> list[Finding]:
    findings: list[Finding] = []
    inspected: set[str] = set()
    for component in graph.components:
        if component.ecosystem != "python":
            continue
        key = component.key(graph.root)
        try:
            workspace = inspect_uv_workspace(graph, component)
        except UvWorkspaceError as exc:
            findings.append(Finding(
                "uv.workspace.invalid",
                "error",
                str(exc),
                key,
                "Fix uv workspace membership before using shared-lock operations or relationship queries.",
            ))
            continue
        if workspace is None:
            continue
        inspected.add(key)
        if not (workspace.root / "uv.lock").is_file():
            findings.append(Finding(
                "uv.workspace.lock-missing",
                "error",
                f"uv workspace {workspace.root} has no shared uv.lock.",
                key,
                "Create/refresh the workspace lock with uv before reproducible sync or relationship analysis.",
            ))
        for pattern in workspace.unmatched_patterns:
            findings.append(Finding(
                "uv.workspace.pattern-unmatched",
                "warning",
                f"uv workspace member pattern {pattern!r} matched no discovered Python component.",
                key,
                "Fix or remove stale uv workspace member patterns.",
            ))

    try:
        uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        message = str(exc)
        code = "uv.workspace.ownership-conflict" if "multiple uv workspaces" in message else "uv.workspace.invalid"
        findings.append(Finding(
            code,
            "error",
            message,
            None,
            "Make uv workspace ownership unambiguous and restore the authoritative shared lock.",
        ))

    unique: dict[tuple[str, str | None, str], Finding] = {}
    for finding in findings:
        unique[(finding.code, finding.component, finding.message)] = finding
    return sorted(unique.values(), key=lambda item: (item.severity, item.code, item.component or "", item.message))
