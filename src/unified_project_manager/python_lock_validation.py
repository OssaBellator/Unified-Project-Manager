from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ProjectGraph
from .python_lock_graph import (
    PythonLockGraphPlan,
    PythonLockGraphResult,
    execute_python_lock_graph,
)


class PythonLockContractError(ValueError):
    """Raised when a lockfile uses relationship semantics UPM has not modeled."""


@dataclass(frozen=True)
class PythonLockContract:
    manager: str
    lockfile: str
    format_version: str | None
    strategies: tuple[str, ...]
    packages: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load(plan: PythonLockGraphPlan) -> dict[str, Any]:
    try:
        with plan.lockfile.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PythonLockContractError(f"Could not read {plan.lockfile}: {exc}") from exc
    if not isinstance(data, dict):
        raise PythonLockContractError(f"{plan.lockfile} root is not a TOML table.")
    return data


def _metadata(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("metadata")
    return value if isinstance(value, dict) else {}


def _format_version(manager: str, metadata: dict[str, Any]) -> str | None:
    keys = ("lock-version", "lock_version") if manager == "poetry" else ("lock_version", "lock-version")
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (str, int, float)):
            return str(value)
    return None


def _strategies(metadata: dict[str, Any]) -> tuple[str, ...]:
    value = metadata.get("strategy")
    if isinstance(value, list):
        return tuple(sorted(item for item in value if isinstance(item, str)))
    if isinstance(value, str):
        return (value,)
    return ()


def _validate_package_conditions(plan: PythonLockGraphPlan, record: dict[str, Any], index: int) -> None:
    # Relationship conditions on dependency edges are modeled. Conditions that
    # qualify the package record itself are not yet part of PythonLockedPackage,
    # so reject them rather than presenting the package as unconditional.
    for key in ("marker", "markers", "target", "targets"):
        value = record.get(key)
        if value not in (None, "", [], {}):
            name = record.get("name") if isinstance(record.get("name"), str) else f"#{index}"
            raise PythonLockContractError(
                f"{plan.lockfile.name} package {name!r} uses record-level {key!r} semantics "
                "that UPM does not yet model; refusing an incomplete relationship graph."
            )


def _validate_poetry_dependencies(plan: PythonLockGraphPlan, record: dict[str, Any], index: int) -> None:
    dependencies = record.get("dependencies")
    if dependencies is None:
        return
    if not isinstance(dependencies, dict):
        raise PythonLockContractError(
            f"{plan.lockfile.name} package #{index} dependencies must be a TOML table for Poetry."
        )
    for name, value in dependencies.items():
        if not isinstance(name, str):
            raise PythonLockContractError(
                f"{plan.lockfile.name} package #{index} contains a non-string dependency name."
            )
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(item, (str, dict)) for item in values):
            raise PythonLockContractError(
                f"{plan.lockfile.name} dependency {name!r} uses an unsupported Poetry constraint shape."
            )


def _validate_pdm_dependencies(plan: PythonLockGraphPlan, record: dict[str, Any], index: int) -> None:
    dependencies = record.get("dependencies")
    if dependencies is None:
        return
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise PythonLockContractError(
            f"{plan.lockfile.name} package #{index} dependencies must be a list of PEP-508 strings for PDM."
        )


def validate_python_lock_plan(plan: PythonLockGraphPlan) -> PythonLockContract:
    if plan.manager not in {"poetry", "pdm"}:
        raise PythonLockContractError(f"Unsupported structured Python lock manager: {plan.manager!r}")
    data = _load(plan)
    records = data.get("package")
    if not isinstance(records, list):
        raise PythonLockContractError(f"{plan.lockfile.name} has no structured package array.")

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise PythonLockContractError(f"{plan.lockfile.name} package #{index} is not a TOML table.")
        _validate_package_conditions(plan, record, index)
        if plan.manager == "poetry":
            _validate_poetry_dependencies(plan, record, index)
        else:
            _validate_pdm_dependencies(plan, record, index)

    metadata = _metadata(data)
    return PythonLockContract(
        manager=plan.manager,
        lockfile=plan.lockfile.name,
        format_version=_format_version(plan.manager, metadata),
        strategies=_strategies(metadata),
        packages=len(records),
    )


def execute_validated_python_lock_graph(
    graph: ProjectGraph,
    plan: PythonLockGraphPlan,
) -> PythonLockGraphResult:
    try:
        validate_python_lock_plan(plan)
    except PythonLockContractError as exc:
        return PythonLockGraphResult(plan, [], [], (), False, str(exc))
    return execute_python_lock_graph(graph, plan)
