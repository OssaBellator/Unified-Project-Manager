from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cargo_workspace import CargoWorkspaceError, cargo_workspace_ownership
from .models import Component, ProjectGraph
from .node_workspace import NodeWorkspaceError, inspect_node_workspace
from .pnpm_workspace import find_pnpm_workspace_root
from .uv_workspace import UvWorkspaceError, uv_workspace_ownership


class PackageWorkspaceScopeError(ValueError):
    """Stable internal signal for workspace ownership facts that block package planning."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        self.code = code
        self.details = dict(sorted((details or {}).items()))
        super().__init__(message)


@dataclass(frozen=True)
class PackageWorkspaceScope:
    kind: str
    root_component: str | None = None
    member_components: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rootComponent": self.root_component,
            "memberComponents": list(self.member_components),
            "issueCodes": list(self.issue_codes),
        }


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix() or "."


def _member_block(selected: Component, graph: ProjectGraph, root_component: str, kind: str) -> PackageWorkspaceScopeError:
    return PackageWorkspaceScopeError(
        "workspace_member_requires_owner",
        f"selected {kind} workspace member must be planned through its authoritative workspace root",
        details={
            "component": selected.key(graph.root),
            "workspaceRootComponent": root_component,
        },
    )


def _pnpm_inspection_required(graph: ProjectGraph, selected: Component, root: Path) -> PackageWorkspaceScopeError:
    return PackageWorkspaceScopeError(
        "workspace_inspection_required",
        "pnpm workspace ownership requires native read-only pnpm inspection before package mutation planning",
        details={
            "component": selected.key(graph.root),
            "workspaceRoot": _relative(graph.root, root),
        },
    )


def _node_scope(graph: ProjectGraph, selected: Component) -> PackageWorkspaceScope:
    selected_path = selected.path.resolve()
    pnpm_root = find_pnpm_workspace_root(selected_path, boundary=graph.root)
    if pnpm_root is not None:
        raise _pnpm_inspection_required(graph, selected, pnpm_root)

    claims: list[tuple[str, PackageWorkspaceScope]] = []
    for component in (item for item in graph.components if item.ecosystem == "node"):
        component_path = component.path.resolve()
        # An invalid package.json workspace can affect the selected component only
        # when the candidate root is the selected path or one of its ancestors.
        try:
            selected_path.relative_to(component_path)
            relevant_ancestor = True
        except ValueError:
            relevant_ancestor = False
        try:
            workspace = inspect_node_workspace(component_path)
        except NodeWorkspaceError as exc:
            if relevant_ancestor:
                raise PackageWorkspaceScopeError(
                    "workspace_ambiguous",
                    "package.json workspace ownership could not be established safely",
                    details={"component": selected.key(graph.root)},
                ) from exc
            continue
        if workspace is None:
            continue

        member_paths = {member.path.resolve() for member in workspace.members}
        if selected_path != workspace.root.resolve() and selected_path not in member_paths:
            continue
        manager = workspace.manager or component.manager
        if manager == "pnpm":
            raise _pnpm_inspection_required(graph, selected, workspace.root)

        root_component = component.key(graph.root)
        members = tuple(
            sorted(
                item.key(graph.root)
                for item in graph.components
                if item.ecosystem == "node" and item.path.resolve() in member_paths
            )
        )
        issue_codes = tuple(sorted({issue.code for issue in workspace.issues}))
        blocking = sorted(code for code in issue_codes if code in {"workspace.manager-mismatch", "workspace.duplicate-package-name"})
        if blocking:
            raise PackageWorkspaceScopeError(
                "workspace_ambiguous",
                "package.json workspace ownership has blocking manager or package-name conflicts",
                details={"component": selected.key(graph.root), "issueCodes": blocking},
            )
        scope = PackageWorkspaceScope("workspace_root", root_component, members, issue_codes)
        claim_kind = "root" if selected_path == workspace.root.resolve() else "member"
        claims.append((claim_kind, scope))

    if len(claims) > 1:
        roots = sorted({scope.root_component for _kind, scope in claims if scope.root_component is not None})
        raise PackageWorkspaceScopeError(
            "workspace_ambiguous",
            "selected Node component is claimed by multiple package.json workspace roots",
            details={"component": selected.key(graph.root), "workspaceRootComponents": roots},
        )
    if not claims:
        return PackageWorkspaceScope("standalone")
    claim_kind, scope = claims[0]
    if claim_kind == "member":
        assert scope.root_component is not None
        raise _member_block(selected, graph, scope.root_component, "Node")
    return scope


def _cargo_scope(graph: ProjectGraph, selected: Component) -> PackageWorkspaceScope:
    try:
        roots, owners = cargo_workspace_ownership(graph)
    except CargoWorkspaceError as exc:
        raise PackageWorkspaceScopeError(
            "workspace_ambiguous",
            "Cargo workspace ownership could not be established safely",
            details={"component": selected.key(graph.root)},
        ) from exc
    selected_path = selected.path.resolve()
    if selected_path in roots and selected_path in owners:
        raise PackageWorkspaceScopeError(
            "workspace_ambiguous",
            "selected Cargo component is both a workspace root and a member of another workspace",
            details={"component": selected.key(graph.root)},
        )
    if selected_path in owners:
        owner = owners[selected_path]
        raise _member_block(selected, graph, owner.root_component, "Cargo")
    root = roots.get(selected_path)
    if root is None:
        return PackageWorkspaceScope("standalone")
    return PackageWorkspaceScope("workspace_root", root.root_component, tuple(sorted(root.members)))


def _uv_scope(graph: ProjectGraph, selected: Component) -> PackageWorkspaceScope:
    try:
        roots, owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise PackageWorkspaceScopeError(
            "workspace_ambiguous",
            "uv workspace ownership could not be established safely",
            details={"component": selected.key(graph.root)},
        ) from exc
    selected_path = selected.path.resolve()
    if selected_path in roots and selected_path in owners:
        raise PackageWorkspaceScopeError(
            "workspace_ambiguous",
            "selected Python component is both a uv workspace root and a member of another workspace",
            details={"component": selected.key(graph.root)},
        )
    if selected_path in owners:
        owner = owners[selected_path]
        raise _member_block(selected, graph, owner.root_component, "uv")
    root = roots.get(selected_path)
    if root is None:
        return PackageWorkspaceScope("standalone")
    return PackageWorkspaceScope("workspace_root", root.root_component, tuple(sorted(root.members)))


def resolve_package_workspace_scope(graph: ProjectGraph, selected: Component) -> PackageWorkspaceScope:
    """Resolve static package-workspace ownership without executing a native manager.

    v1 accepts standalone components and authoritative static workspace roots. A
    selected workspace member is refused rather than rewritten to a broader root
    operation. pnpm ownership is intentionally not inferred from files alone.
    """

    if selected.ecosystem == "node":
        return _node_scope(graph, selected)
    if selected.ecosystem == "rust":
        return _cargo_scope(graph, selected)
    if selected.ecosystem == "python":
        return _uv_scope(graph, selected)
    return PackageWorkspaceScope("standalone")
