from __future__ import annotations

from collections.abc import Iterable

from .models import CommandPlan, ProjectGraph
from .operations import OperationError, plan_operation
from .pnpm_workspace import PnpmWorkspaceResult
from .workspace_batch import WorkspaceBatchError, WorkspaceBatchOperation, WorkspaceBatchResult, plan_workspace_batch


def plan_all_operations(
    graph: ProjectGraph,
    operation: WorkspaceBatchOperation,
    *,
    pnpm_results: Iterable[PnpmWorkspaceResult] = (),
) -> tuple[list[CommandPlan], WorkspaceBatchResult]:
    """Plan install/sync across a mixed project without double-running workspace members.

    Workspace-owned Node components collapse to the authoritative workspace root.
    Components that are not consumed by a workspace are planned through the same
    single-component operation planner used by normal UPM mutations.
    """
    batch = plan_workspace_batch(graph, operation, pnpm_results=pnpm_results)
    plans: list[CommandPlan] = []

    for workspace in batch.workspace_plans:
        plans.append(CommandPlan(
            operation=operation,
            component=workspace.owner,
            manager=workspace.manager,
            argv=workspace.argv,
            cwd=workspace.cwd,
        ))

    for component_key in batch.standalone_components:
        try:
            plans.append(plan_operation(graph, operation, selector=component_key))
        except OperationError as exc:
            raise WorkspaceBatchError(f"Cannot plan standalone component {component_key}: {exc}") from exc

    if not plans:
        raise WorkspaceBatchError("No supported project components were discovered for the batch operation.")

    plans.sort(key=lambda plan: (
        plan.cwd.relative_to(graph.root).as_posix(),
        plan.manager,
        plan.component,
    ))
    return plans, batch
