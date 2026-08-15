from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ProjectGraph
from .native_exec import NativeExecError, NativeExecPlan, plan_native_exec
from .operations import OperationError, select_component


class DedupeOperationError(ValueError):
    """Raised when a component has no safe first-party native dedupe operation."""


@dataclass(frozen=True)
class DedupePlan:
    native: NativeExecPlan
    manifest_may_change: bool
    native_state_may_change: bool
    installed_state_may_change: bool
    network_may_be_used: bool
    semantics: str

    @property
    def component(self) -> str:
        return self.native.component

    @property
    def manager(self) -> str:
        return self.native.manager

    @property
    def cwd(self):
        return self.native.cwd

    @property
    def argv(self) -> tuple[str, ...]:
        return self.native.argv

    def to_dict(self, root) -> dict[str, Any]:
        return {
            **self.native.to_dict(root),
            "manifest_may_change": self.manifest_may_change,
            "native_state_may_change": self.native_state_may_change,
            "installed_state_may_change": self.installed_state_may_change,
            "network_may_be_used": self.network_may_be_used,
            "semantics": self.semantics,
        }


def _yarn_major(component) -> int | None:
    declared = component.metadata.get("package_manager_declared")
    if not isinstance(declared, str) or not declared.startswith("yarn@"):
        return None
    text = declared.removeprefix("yarn@").split("-", 1)[0]
    try:
        return int(text.split(".", 1)[0])
    except ValueError:
        return None


def plan_dedupe(graph: ProjectGraph, *, selector: str | None = None) -> DedupePlan:
    try:
        component = select_component(graph, selector)
    except OperationError as exc:
        raise DedupeOperationError(str(exc)) from exc
    if component.ecosystem != "node":
        raise DedupeOperationError(
            f"No generic dedupe mutation is defined for {component.ecosystem}; use duplicate analysis and the ecosystem's authoritative resolver/update workflow."
        )
    manager = component.manager
    if manager == "npm":
        arguments = ("dedupe",)
        semantics = "asks npm to reduce duplication in the installed dependency tree while preserving declared dependency requirements"
    elif manager == "pnpm":
        arguments = ("dedupe",)
        semantics = "asks pnpm to deduplicate dependency resolutions using pnpm's native compatibility rules"
    elif manager == "yarn":
        major = _yarn_major(component)
        if major is not None and major <= 1:
            raise DedupeOperationError(
                "Yarn Classic has no UPM-configured first-party dedupe operation; use duplicate analysis or an explicit project workflow."
            )
        arguments = ("dedupe",)
        semantics = "asks modern Yarn to deduplicate overlapping dependency ranges using Yarn's native strategy"
    else:
        raise DedupeOperationError(
            f"No UPM-configured first-party dedupe operation exists for Node manager {manager!r}."
        )

    try:
        native = plan_native_exec(graph, arguments, selector=component.key(graph.root))
    except NativeExecError as exc:
        raise DedupeOperationError(str(exc)) from exc
    return DedupePlan(
        native=native,
        manifest_may_change=False,
        native_state_may_change=True,
        installed_state_may_change=True,
        network_may_be_used=True,
        semantics=semantics,
    )
