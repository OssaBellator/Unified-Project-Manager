from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class VerificationError(ValueError):
    """Raised when a requested native verification cannot be selected safely."""


@dataclass(frozen=True)
class VerificationPlan:
    component: str
    manager: str
    argv: tuple[str, ...]
    cwd: Path

    def to_dict(self, root: Path) -> dict[str, Any]:
        try:
            cwd = self.cwd.relative_to(root).as_posix() or "."
        except ValueError:
            cwd = str(self.cwd)
        return {"component": self.component, "manager": self.manager, "argv": list(self.argv), "cwd": cwd}


@dataclass(frozen=True)
class VerificationSkip:
    component: str
    manager: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    plan: VerificationPlan
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _native_argv(component: Component) -> tuple[str, ...] | None:
    manager = component.manager
    if manager == "npm" and any(name in component.lockfiles for name in ("package-lock.json", "npm-shrinkwrap.json")):
        return ("npm", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--fund=false")
    if manager == "bun" and any(name in component.lockfiles for name in ("bun.lock", "bun.lockb")):
        return ("bun", "install", "--frozen-lockfile", "--dry-run", "--ignore-scripts")
    if manager == "uv" and "uv.lock" in component.lockfiles:
        return ("uv", "lock", "--check")
    if manager == "pdm" and "pdm.lock" in component.lockfiles:
        return ("pdm", "lock", "--check")
    if manager == "cargo" and "Cargo.lock" in component.lockfiles:
        return ("cargo", "metadata", "--locked", "--no-deps", "--format-version", "1")
    if manager == "go":
        return ("go", "mod", "tidy", "-diff")
    return None


def _select(graph: ProjectGraph, selector: str | None) -> list[Component]:
    if selector is None:
        return list(graph.components)
    matches = [component for component in graph.components if selector in {
        component.key(graph.root), component.relative_path(graph.root), component.ecosystem,
        component.metadata.get("name"),
    }]
    if not matches:
        raise VerificationError(f"Unknown component '{selector}'.")
    if len(matches) > 1:
        choices = ", ".join(component.key(graph.root) for component in matches)
        raise VerificationError(f"Component selector '{selector}' is ambiguous: {choices}")
    return matches


def plan_native_verification(graph: ProjectGraph, selector: str | None = None) -> tuple[list[VerificationPlan], list[VerificationSkip]]:
    plans: list[VerificationPlan] = []
    skips: list[VerificationSkip] = []
    for component in _select(graph, selector):
        key = component.key(graph.root)
        if component.metadata.get("parse_error"):
            skips.append(VerificationSkip(key, component.manager, "manifest is invalid"))
            continue
        if component.manager != "go" and len(component.lockfiles) != 1:
            reason = "no native lockfile" if not component.lockfiles else "conflicting native lockfiles"
            skips.append(VerificationSkip(key, component.manager, reason))
            continue
        if component.manager == "go" and len(component.lockfiles) > 1:
            skips.append(VerificationSkip(key, component.manager, "conflicting native lockfiles"))
            continue
        argv = _native_argv(component)
        if argv is None:
            skips.append(VerificationSkip(key, component.manager, "no documented non-mutating native verifier is configured"))
            continue
        assert component.manager is not None
        plans.append(VerificationPlan(key, component.manager, argv, component.path))
    return plans, skips


def execute_verification(
    plan: VerificationPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> VerificationResult:
    executable = which(plan.argv[0])
    if executable is None:
        return VerificationResult(plan, 127, stderr=f"Executable '{plan.argv[0]}' is not available on PATH.")
    argv = [executable, *plan.argv[1:]]
    kwargs: dict[str, Any] = {
        "cwd": plan.cwd,
        "text": True,
        "capture_output": True,
        "check": False,
    }
    if plan.manager == "go":
        env = dict(os.environ)
        env["GOWORK"] = "off"
        kwargs["env"] = env
    try:
        completed = run(argv, **kwargs)
    except OSError as exc:
        return VerificationResult(plan, 127, stderr=str(exc))
    return VerificationResult(plan, completed.returncode, completed.stdout or "", completed.stderr or "")
