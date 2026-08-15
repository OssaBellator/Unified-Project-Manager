from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from .models import ProjectGraph
from .pnpm_workspace import PnpmWorkspacePlan, PnpmWorkspaceResult, plan_pnpm_workspace
from .workspace_operations import WorkspaceOperationError, plan_node_workspace_operations

WorkspaceBatchOperation = Literal["install", "sync"]


class WorkspaceBatchError(ValueError):
    """Raised when workspace ownership cannot be collapsed safely."""


class WorkspaceInspectionRequired(WorkspaceBatchError):
    """Raised when native workspace inspection is required before batch planning."""

    def __init__(self, roots: Iterable[Path]):
        self.roots = tuple(sorted({path.resolve() for path in roots}, key=str))
        rendered = ", ".join(str(path) for path in self.roots)
        super().__init__(f"Native pnpm workspace inspection is required before batch planning: {rendered}")


@dataclass(frozen=True)
class WorkspaceBatchPlan:
    operation: WorkspaceBatchOperation
    workspace_kind: str
    manager: str
    cwd: Path
    argv: tuple[str, ...]
    owner: str
    member_components: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        data = asdict(self)
        data["cwd"] = self.cwd.relative_to(root).as_posix() or "."
        data["argv"] = list(self.argv)
        data["member_components"] = list(self.member_components)
        return data


@dataclass(frozen=True)
class WorkspaceBatchResult:
    operation: WorkspaceBatchOperation
    workspace_plans: tuple[WorkspaceBatchPlan, ...]
    consumed_components: tuple[str, ...]
    standalone_components: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "workspace_plans": [plan.to_dict(root) for plan in self.workspace_plans],
            "consumed_components": list(self.consumed_components),
            "standalone_components": list(self.standalone_components),
        }


def required_pnpm_workspace_inspections(graph: ProjectGraph) -> list[PnpmWorkspacePlan]:
    roots: dict[Path, PnpmWorkspacePlan] = {}
    for component in graph.components:
        if component.ecosystem != "node":
            continue
        plan = plan_pnpm_workspace(component.path, graph.root)
        if plan is not None:
            roots.setdefault(plan.root.resolve(), plan)
    return [roots[root] for root in sorted(roots, key=str)]


def _pnpm_argv(operation: WorkspaceBatchOperation) -> tuple[str, ...]:
    if operation == "install":
        return ("pnpm", "install")
    if operation == "sync":
        return ("pnpm", "install", "--frozen-lockfile")
    raise WorkspaceBatchError(f"Unsupported workspace batch operation {operation!r}.")


def plan_workspace_batch(
    graph: ProjectGraph,
    operation: WorkspaceBatchOperation,
    *,
    pnpm_results: Iterable[PnpmWorkspaceResult] = (),
) -> WorkspaceBatchResult:
    if operation not in {"install", "sync"}:
        raise WorkspaceBatchError(f"Unsupported workspace batch operation {operation!r}.")

    try:
        package_json_plans, consumed = plan_node_workspace_operations(graph, operation)
    except WorkspaceOperationError as exc:
        raise WorkspaceBatchError(str(exc)) from exc

    plans: list[WorkspaceBatchPlan] = [
        WorkspaceBatchPlan(
            operation=operation,
            workspace_kind="package-json",
            manager=plan.manager,
            cwd=plan.cwd,
            argv=plan.argv,
            owner=plan.workspace_root_component,
            member_components=plan.member_components,
        )
        for plan in package_json_plans
    ]
    consumed = set(consumed)

    supplied: dict[Path, PnpmWorkspaceResult] = {}
    for result in pnpm_results:
        root = result.plan.root.resolve()
        if root in supplied:
            raise WorkspaceBatchError(f"Duplicate pnpm workspace inspection result for {root}.")
        if not result.succeeded:
            detail = result.stderr.strip() or f"pnpm exited with {result.returncode}"
            raise WorkspaceBatchError(f"pnpm workspace inspection failed for {root}: {detail}")
        supplied[root] = result

    required = {plan.root.resolve(): plan for plan in required_pnpm_workspace_inspections(graph)}
    missing = [root for root in required if root not in supplied]
    if missing:
        raise WorkspaceInspectionRequired(missing)

    node_by_path = {
        component.path.resolve(): component
        for component in graph.components
        if component.ecosystem == "node"
    }

    for root in sorted(required, key=str):
        result = supplied[root]
        try:
            relative_root = root.relative_to(graph.root)
        except ValueError as exc:
            raise WorkspaceBatchError(f"pnpm workspace root escapes the project root: {root}") from exc

        root_component = node_by_path.get(root)
        if root_component is not None and root_component.manager not in {None, "pnpm"}:
            raise WorkspaceBatchError(
                f"pnpm workspace root {root_component.key(graph.root)} is owned by {root_component.manager}."
            )
        if operation == "sync" and not (root / "pnpm-lock.yaml").is_file():
            raise WorkspaceBatchError(f"pnpm workspace {root} has no pnpm-lock.yaml for frozen sync.")

        owned_keys: set[str] = set()
        if root_component is not None:
            owned_keys.add(root_component.key(graph.root))

        for member in result.members:
            member_path = member.path.resolve()
            try:
                member_path.relative_to(root)
                member_path.relative_to(graph.root)
            except ValueError as exc:
                raise WorkspaceBatchError(
                    f"pnpm workspace inspection returned member outside the selected workspace/project root: {member_path}"
                ) from exc
            component = node_by_path.get(member_path)
            if component is None:
                if (member_path / "package.json").is_file():
                    raise WorkspaceBatchError(
                        f"pnpm workspace member was not discovered as a Node component: {member_path}"
                    )
                continue
            if component.manager not in {None, "pnpm"}:
                raise WorkspaceBatchError(
                    f"pnpm workspace member {component.key(graph.root)} is owned by {component.manager}."
                )
            owned_keys.add(component.key(graph.root))

        overlap = consumed & owned_keys
        if overlap:
            raise WorkspaceBatchError(
                "Overlapping workspace ownership detected: " + ", ".join(sorted(overlap))
            )
        consumed.update(owned_keys)
        owner = root_component.key(graph.root) if root_component is not None else f"workspace:{relative_root.as_posix() or '.'}:pnpm"
        members = tuple(sorted(key for key in owned_keys if key != owner))
        plans.append(WorkspaceBatchPlan(
            operation=operation,
            workspace_kind="pnpm",
            manager="pnpm",
            cwd=root,
            argv=_pnpm_argv(operation),
            owner=owner,
            member_components=members,
        ))

    all_keys = {component.key(graph.root) for component in graph.components}
    standalone = tuple(sorted(all_keys - consumed))
    plans.sort(key=lambda plan: (plan.cwd.relative_to(graph.root).as_posix(), plan.workspace_kind))
    return WorkspaceBatchResult(
        operation=operation,
        workspace_plans=tuple(plans),
        consumed_components=tuple(sorted(consumed)),
        standalone_components=standalone,
    )
