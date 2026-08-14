from __future__ import annotations

from .models import CommandPlan, DoctorReport, ProjectGraph
from .operations import OperationError, plan_operation, select_component

REPAIRABLE_INSTALLED_CODES = {
    "installed.metadata-missing",
    "installed.metadata-invalid",
    "installed.version-mismatch",
    "installed.package-missing",
    "installed.package-untracked",
}


class RepairError(ValueError):
    """Raised when UPM cannot derive a safe repair plan."""


def plan_repairs(graph: ProjectGraph, report: DoctorReport, selector: str | None = None) -> list[CommandPlan]:
    selected_key: str | None = None
    if selector is not None:
        try:
            selected_key = select_component(graph, selector).key(graph.root)
        except OperationError as exc:
            raise RepairError(str(exc)) from exc

    affected = sorted({
        finding.component
        for finding in report.findings
        if finding.code in REPAIRABLE_INSTALLED_CODES and finding.component is not None
        and (selected_key is None or finding.component == selected_key)
    })
    plans: list[CommandPlan] = []
    errors: list[str] = []
    for component_key in affected:
        try:
            plans.append(plan_operation(graph, "sync", selector=component_key))
        except OperationError as exc:
            errors.append(f"{component_key}: {exc}")
    if errors:
        raise RepairError("Some detected installed-state drift cannot be repaired safely: " + "; ".join(errors))
    return plans
