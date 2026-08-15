from __future__ import annotations

from pathlib import Path

from .cargo_workspace import CargoWorkspaceError, cargo_workspace_ownership, inspect_cargo_workspace
from .models import Finding, ProjectGraph
from .node_workspace import NodeWorkspaceError, inspect_node_workspace
from .uv_workspace_health import uv_workspace_findings


_SEVERITY = {
    'workspace.manager-mismatch': 'error',
    'workspace.duplicate-package-name': 'error',
    'workspace.pattern-unmatched': 'warning',
    'workspace.unlisted-package': 'warning',
}

_HINTS = {
    'workspace.manager-mismatch': 'Align package-manager ownership at the workspace root/member boundary before batch mutation.',
    'workspace.duplicate-package-name': 'Give every workspace member a unique package name.',
    'workspace.pattern-unmatched': 'Fix or remove stale workspace patterns so membership matches the repository.',
    'workspace.unlisted-package': 'Add the nested package to the workspace declaration or move it outside the workspace root.',
}


def node_workspace_findings(graph: ProjectGraph) -> list[Finding]:
    findings: list[Finding] = []
    inspected: set[Path] = set()
    for component in graph.components:
        if component.ecosystem != 'node':
            continue
        root = component.path.resolve()
        if root in inspected:
            continue
        try:
            workspace = inspect_node_workspace(root)
        except NodeWorkspaceError as exc:
            findings.append(Finding(
                'workspace.invalid',
                'error',
                str(exc),
                component.key(graph.root),
                'Fix the package.json workspace declaration before workspace-owned operations.',
            ))
            inspected.add(root)
            continue
        if workspace is None:
            continue
        inspected.add(root)
        component_key = component.key(graph.root)
        for issue in workspace.issues:
            location = component_key
            if issue.path:
                location = f'{component_key}::{issue.path}'
            findings.append(Finding(
                issue.code,
                _SEVERITY.get(issue.code, 'info'),
                issue.message,
                location,
                _HINTS.get(issue.code),
            ))
    return sorted(findings, key=lambda item: (item.severity, item.code, item.component or '', item.message))


def cargo_workspace_findings(graph: ProjectGraph) -> list[Finding]:
    findings: list[Finding] = []
    for component in graph.components:
        if component.ecosystem != 'rust' or not component.metadata.get('workspace'):
            continue
        try:
            workspace = inspect_cargo_workspace(graph, component)
        except CargoWorkspaceError as exc:
            findings.append(Finding(
                'cargo.workspace.invalid',
                'error',
                str(exc),
                component.key(graph.root),
                'Fix the Cargo workspace manifest before relying on workspace-owned graph or mutation behavior.',
            ))
            continue
        if workspace is None:
            continue
        for pattern in workspace.unmatched_member_patterns:
            findings.append(Finding(
                'cargo.workspace.pattern-unmatched',
                'warning',
                f"Cargo workspace member pattern {pattern!r} matched no discovered Cargo component.",
                component.key(graph.root),
                'Fix or remove stale Cargo workspace member patterns.',
            ))
    try:
        cargo_workspace_ownership(graph)
    except CargoWorkspaceError as exc:
        findings.append(Finding(
            'cargo.workspace.ownership-conflict',
            'error',
            str(exc),
            None,
            'Make Cargo workspace ownership unambiguous before native graph queries.',
        ))
    return sorted(findings, key=lambda item: (item.severity, item.code, item.component or '', item.message))


def workspace_findings(graph: ProjectGraph) -> list[Finding]:
    return sorted(
        [
            *node_workspace_findings(graph),
            *cargo_workspace_findings(graph),
            *uv_workspace_findings(graph),
        ],
        key=lambda item: (item.severity, item.code, item.component or '', item.message),
    )
