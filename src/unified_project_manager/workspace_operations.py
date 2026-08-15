from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .models import ProjectGraph
from .node_workspace import NodeWorkspaceError, inspect_node_workspace

WorkspaceOperation = Literal["install", "sync"]


class WorkspaceOperationError(ValueError):
    """Raised when a workspace-owned batch operation cannot be planned safely."""


@dataclass(frozen=True)
class WorkspaceOperationPlan:
    operation: WorkspaceOperation
    manager: str
    cwd: Path
    argv: tuple[str, ...]
    workspace_root_component: str
    member_components: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        data = asdict(self)
        data["cwd"] = self.cwd.relative_to(root).as_posix() or "."
        data["argv"] = list(self.argv)
        data["member_components"] = list(self.member_components)
        return data


def _argv(manager: str, operation: WorkspaceOperation) -> tuple[str, ...]:
    if manager == "npm":
        return ("npm", "install") if operation == "install" else ("npm", "ci")
    if manager == "yarn":
        return ("yarn", "install") if operation == "install" else ("yarn", "install", "--immutable")
    if manager == "bun":
        return ("bun", "install") if operation == "install" else ("bun", "install", "--frozen-lockfile")
    raise WorkspaceOperationError(
        f"Workspace-owned {operation} is not configured for manager {manager!r}; "
        "pnpm workspace ownership requires native pnpm workspace modeling rather than package.json-only inference."
    )


def plan_node_workspace_operations(
    graph: ProjectGraph,
    operation: WorkspaceOperation,
) -> tuple[list[WorkspaceOperationPlan], set[str]]:
    """Return authoritative package.json-workspace plans plus consumed component keys.

    The returned consumed set lets a future `--all` planner avoid scheduling the
    same Node workspace member as an independent install/sync after the root has
    already taken ownership of the operation.
    """
    if operation not in {"install", "sync"}:
        raise WorkspaceOperationError(f"Unsupported workspace operation {operation!r}.")

    plans: list[WorkspaceOperationPlan] = []
    consumed: set[str] = set()
    node_components = [component for component in graph.components if component.ecosystem == "node"]
    by_path = {component.path.resolve(): component for component in node_components}

    for root_component in node_components:
        root_path = root_component.path.resolve()
        if root_path in consumed:
            continue
        try:
            workspace = inspect_node_workspace(root_path)
        except NodeWorkspaceError as exc:
            raise WorkspaceOperationError(str(exc)) from exc
        if workspace is None:
            continue
        manager = workspace.manager or root_component.manager
        if manager not in {"npm", "yarn", "bun"}:
            # package.json workspaces are not enough to prove pnpm workspace ownership.
            continue
        if root_component.manager and manager != root_component.manager:
            raise WorkspaceOperationError(
                f"Workspace root {root_component.key(graph.root)} declares {manager}, "
                f"but discovery inferred {root_component.manager}."
            )
        if operation == "sync" and not root_component.lockfiles:
            raise WorkspaceOperationError(
                f"Workspace root {root_component.key(graph.root)} has no native lockfile for reproducible sync."
            )

        member_keys: list[str] = []
        for member in workspace.members:
            component = by_path.get(member.path.resolve())
            if component is None:
                continue
            if component.manager and component.manager != manager:
                raise WorkspaceOperationError(
                    f"Workspace member {component.key(graph.root)} is owned by {component.manager}, "
                    f"not workspace manager {manager}."
                )
            member_keys.append(component.key(graph.root))

        root_key = root_component.key(graph.root)
        owned = {root_key, *member_keys}
        if consumed & owned:
            overlap = ", ".join(sorted(consumed & owned))
            raise WorkspaceOperationError(f"Overlapping package.json workspace ownership detected: {overlap}")
        consumed.update(owned)
        plans.append(WorkspaceOperationPlan(
            operation=operation,
            manager=manager,
            cwd=root_path,
            argv=_argv(manager, operation),
            workspace_root_component=root_key,
            member_components=tuple(sorted(member_keys)),
        ))

    plans.sort(key=lambda plan: plan.cwd.relative_to(graph.root).as_posix())
    return plans, consumed
