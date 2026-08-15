from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .models import Component, ProjectGraph
from .npm_graph import NpmGraphError, plan_npm_graphs

NpmSbomFormat = Literal["cyclonedx", "spdx"]


class NpmSbomError(ValueError):
    """Raised when npm native SBOM planning or parsing is unsafe/invalid."""


@dataclass(frozen=True)
class NpmSbomPlan:
    component: str
    cwd: Path
    format: NpmSbomFormat
    workspace_selector: str | None = None

    @property
    def argv(self) -> tuple[str, ...]:
        args: list[str] = ["npm", "sbom", "--sbom-format", self.format, "--package-lock-only"]
        if self.workspace_selector:
            args.extend(("--workspace", self.workspace_selector))
        return tuple(args)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "npm",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "format": self.format,
            "argv": list(self.argv),
            "source": "npm native SBOM from package-lock",
            "package_lock_only": True,
            "workspace_selector": self.workspace_selector,
            "network": False,
            "mutates_project": False,
        }


@dataclass
class NpmSbomResult:
    plan: NpmSbomPlan
    document: dict[str, Any] | None
    returncode: int
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and self.document is not None

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "has_document": self.document is not None,
            "stderr": self.stderr,
        }


def plan_npm_sboms(
    graph: ProjectGraph,
    format: NpmSbomFormat,
    selector: str | None = None,
) -> list[NpmSbomPlan]:
    if format not in {"cyclonedx", "spdx"}:
        raise NpmSbomError(f"Unsupported npm SBOM format {format!r}.")
    try:
        graph_plans = plan_npm_graphs(graph, selector=selector)
    except NpmGraphError as exc:
        raise NpmSbomError(str(exc)) from exc
    return [
        NpmSbomPlan(
            component=plan.component,
            cwd=plan.cwd,
            format=format,
            workspace_selector=plan.workspace_selector,
        )
        for plan in graph_plans
    ]


def parse_npm_sbom_output(text: str, format: NpmSbomFormat) -> dict[str, Any]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NpmSbomError(f"Could not parse npm SBOM JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise NpmSbomError("npm SBOM JSON root is not an object.")
    if format == "cyclonedx" and document.get("bomFormat") != "CycloneDX":
        raise NpmSbomError("npm CycloneDX provider returned a non-CycloneDX document.")
    if format == "spdx" and document.get("spdxVersion") != "SPDX-2.3":
        raise NpmSbomError("npm SPDX provider returned a non-SPDX-2.3 document.")
    return document


def execute_npm_sbom(
    plan: NpmSbomPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> NpmSbomResult:
    executable = which("npm")
    if executable is None:
        return NpmSbomResult(plan, None, 127, "Executable 'npm' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return NpmSbomResult(plan, None, 127, str(exc))
    if completed.returncode != 0:
        return NpmSbomResult(plan, None, completed.returncode, (completed.stderr or "").strip())
    try:
        document = parse_npm_sbom_output(completed.stdout or "", plan.format)
    except NpmSbomError as exc:
        return NpmSbomResult(plan, None, 1, str(exc))
    return NpmSbomResult(plan, document, 0, (completed.stderr or "").strip())
