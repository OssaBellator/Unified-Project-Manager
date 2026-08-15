from __future__ import annotations

from .models import Finding, ProjectGraph
from .uv_workspace_health import uv_workspace_findings
from .workspace_health import workspace_findings


def all_workspace_findings(graph: ProjectGraph) -> list[Finding]:
    """Return all currently modeled workspace health evidence without native execution."""
    findings = [*workspace_findings(graph), *uv_workspace_findings(graph)]
    unique: dict[tuple[str, str | None, str], Finding] = {}
    for finding in findings:
        unique[(finding.code, finding.component, finding.message)] = finding
    return sorted(unique.values(), key=lambda item: (
        item.severity, item.code, item.component or "", item.message
    ))
