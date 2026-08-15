from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .discovery import discover
from .doctor import diagnose
from .models import DoctorReport, Component, ProjectGraph
from .operations import OperationError, select_component


class NativeExecError(ValueError):
    """Raised when a native manager escape-hatch command cannot be planned safely."""


_MANAGER_PREFIXES: dict[str, tuple[str, ...]] = {
    "npm": ("npm",),
    "pnpm": ("pnpm",),
    "yarn": ("yarn",),
    "bun": ("bun",),
    "uv": ("uv",),
    "poetry": ("poetry",),
    "pdm": ("pdm",),
    "pip": ("python", "-m", "pip"),
    "cargo": ("cargo",),
    "go": ("go",),
}


@dataclass(frozen=True)
class NativeExecPlan:
    component: str
    ecosystem: str
    manager: str
    argv: tuple[str, ...]
    cwd: Path

    def to_dict(self, root: Path) -> dict[str, Any]:
        try:
            cwd = self.cwd.relative_to(root).as_posix() or "."
        except ValueError:
            cwd = str(self.cwd)
        return {
            "component": self.component,
            "ecosystem": self.ecosystem,
            "manager": self.manager,
            "argv": list(self.argv),
            "cwd": cwd,
        }


@dataclass
class NativeExecResult:
    plan: NativeExecPlan
    returncode: int
    stdout: str = ""
    stderr: str = ""
    verification: DoctorReport | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not (self.verification and self.verification.errors)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "verification": self.verification.to_dict() if self.verification else None,
        }


def _validate_manager_ownership(component: Component) -> None:
    if component.metadata.get("parse_error"):
        raise NativeExecError("Cannot exec through a component with an invalid manifest.")
    if len(component.lockfiles) > 1:
        raise NativeExecError(
            "Cannot choose an authoritative manager while multiple native lockfiles are present: "
            + ", ".join(component.lockfiles)
        )
    declarations = component.metadata.get("manager_declarations")
    if isinstance(declarations, list) and len(declarations) > 1:
        raise NativeExecError(
            "Cannot choose an authoritative manager while multiple managers are declared: "
            + ", ".join(map(str, declarations))
        )
    declared = component.metadata.get("manager_from_manifest")
    locked = component.metadata.get("manager_from_lock")
    if declared and locked and declared != locked:
        raise NativeExecError(
            f"Cannot choose an authoritative manager: manifest declares {declared} but native state belongs to {locked}."
        )


def plan_native_exec(
    graph: ProjectGraph,
    arguments: Sequence[str],
    *,
    selector: str | None = None,
) -> NativeExecPlan:
    try:
        component = select_component(graph, selector)
    except OperationError as exc:
        raise NativeExecError(str(exc)) from exc
    _validate_manager_ownership(component)
    if not arguments:
        raise NativeExecError("Native exec requires manager arguments after '--'.")
    manager = component.manager
    if manager is None:
        raise NativeExecError("Cannot exec because this component's native manager is unknown.")
    prefix = _MANAGER_PREFIXES.get(manager)
    if prefix is None:
        raise NativeExecError(f"Native exec is not configured for package manager '{manager}'.")
    return NativeExecPlan(
        component=component.key(graph.root),
        ecosystem=component.ecosystem,
        manager=manager,
        argv=(*prefix, *tuple(arguments)),
        cwd=component.path,
    )


def execute_native_exec(
    plan: NativeExecPlan,
    root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    verify: bool = True,
) -> NativeExecResult:
    executable = which(plan.argv[0])
    if executable is None:
        return NativeExecResult(plan, 127, stderr=f"Executable '{plan.argv[0]}' is not available on PATH.")
    argv = [executable, *plan.argv[1:]]
    try:
        completed = run(argv, cwd=plan.cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return NativeExecResult(plan, 127, stderr=str(exc))
    result = NativeExecResult(
        plan,
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )
    if completed.returncode == 0 and verify:
        result.verification = diagnose(discover(root), which=which)
    return result
