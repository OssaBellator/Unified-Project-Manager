from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .models import ProjectGraph
from .uv_workspace import UvWorkspaceError, uv_workspace_ownership

UvWorkspaceOperation = Literal["install", "sync"]


class UvWorkspaceOperationError(ValueError):
    """Raised when a shared uv workspace operation cannot be planned safely."""


@dataclass(frozen=True)
class UvWorkspaceOperationPlan:
    operation: UvWorkspaceOperation
    component: str
    cwd: Path
    argv: tuple[str, ...]
    member_components: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        data = asdict(self)
        data["cwd"] = self.cwd.relative_to(root).as_posix() or "."
        data["argv"] = list(self.argv)
        data["member_components"] = list(self.member_components)
        return data


def _argv(operation: UvWorkspaceOperation) -> tuple[str, ...]:
    if operation == "install":
        return ("uv", "sync", "--all-packages")
    if operation == "sync":
        return ("uv", "sync", "--all-packages", "--locked")
    raise UvWorkspaceOperationError(f"Unsupported uv workspace operation {operation!r}.")


def plan_uv_workspace_operations(
    graph: ProjectGraph,
    operation: UvWorkspaceOperation,
) -> tuple[list[UvWorkspaceOperationPlan], set[str]]:
    if operation not in {"install", "sync"}:
        raise UvWorkspaceOperationError(f"Unsupported uv workspace operation {operation!r}.")
    try:
        roots, _owners = uv_workspace_ownership(graph)
    except UvWorkspaceError as exc:
        raise UvWorkspaceOperationError(str(exc)) from exc

    plans: list[UvWorkspaceOperationPlan] = []
    consumed: set[str] = set()
    for root in sorted(roots, key=str):
        workspace = roots[root]
        if operation == "sync" and not (root / "uv.lock").is_file():
            raise UvWorkspaceOperationError(f"uv workspace {root} has no uv.lock for locked synchronization.")
        overlap = consumed.intersection(workspace.members)
        if overlap:
            raise UvWorkspaceOperationError(
                "Overlapping uv workspace ownership detected: " + ", ".join(sorted(overlap))
            )
        consumed.update(workspace.members)
        plans.append(UvWorkspaceOperationPlan(
            operation=operation,
            component=workspace.root_component,
            cwd=root,
            argv=_argv(operation),
            member_components=tuple(key for key in workspace.members if key != workspace.root_component),
        ))
    return plans, consumed
