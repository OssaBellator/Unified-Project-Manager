from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .models import Component, ProjectGraph
from .pnpm_workspace import find_pnpm_workspace_root

PnpmSbomFormat = Literal["cyclonedx", "spdx"]


class PnpmSbomError(ValueError):
    """Raised when pnpm native SBOM planning or parsing is unsafe/invalid."""


@dataclass(frozen=True)
class PnpmSbomPlan:
    component: str
    cwd: Path
    format: PnpmSbomFormat
    split: bool = False
    filter_selector: str | None = None

    @property
    def argv(self) -> tuple[str, ...]:
        args: list[str] = ["pnpm", "sbom", "--sbom-format", self.format, "--lockfile-only"]
        if self.split:
            args.append("--split")
        if self.filter_selector:
            args.extend(("--filter", self.filter_selector))
        return tuple(args)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "pnpm",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "format": self.format,
            "argv": list(self.argv),
            "source": "pnpm native SBOM from pnpm-lock.yaml",
            "lockfile_only": True,
            "store_read": False,
            "split": self.split,
            "filter": self.filter_selector,
        }


@dataclass
class PnpmSbomResult:
    plan: PnpmSbomPlan
    documents: list[dict[str, Any]]
    returncode: int
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "documents": len(self.documents),
            "stderr": self.stderr,
        }


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _filter_for_component(component: Component, workspace_root: Path) -> str:
    name = component.metadata.get("name")
    if isinstance(name, str) and name:
        return name
    relative = component.path.resolve().relative_to(workspace_root.resolve()).as_posix() or "."
    return "." if relative == "." else f"./{relative}"


def _plan_for_component(
    graph: ProjectGraph,
    component: Component,
    format: PnpmSbomFormat,
    *,
    selected: bool,
) -> PnpmSbomPlan | None:
    workspace_root = find_pnpm_workspace_root(component.path, graph.root)
    by_path = {
        item.path.resolve(): item
        for item in graph.components
        if item.ecosystem == "node"
    }
    if workspace_root is not None:
        owner = by_path.get(workspace_root.resolve())
        if owner is None or owner.manager != "pnpm" or not (workspace_root / "pnpm-lock.yaml").is_file():
            return None
        if selected:
            return PnpmSbomPlan(
                owner.key(graph.root),
                workspace_root,
                format,
                split=False,
                filter_selector=_filter_for_component(component, workspace_root),
            )
        return PnpmSbomPlan(owner.key(graph.root), workspace_root, format, split=True)
    if component.manager == "pnpm" and "pnpm-lock.yaml" in component.lockfiles:
        return PnpmSbomPlan(component.key(graph.root), component.path, format)
    return None


def plan_pnpm_sboms(
    graph: ProjectGraph,
    format: PnpmSbomFormat,
    selector: str | None = None,
) -> list[PnpmSbomPlan]:
    if format not in {"cyclonedx", "spdx"}:
        raise PnpmSbomError(f"Unsupported pnpm SBOM format {format!r}.")
    nodes = [component for component in graph.components if component.ecosystem == "node"]
    if selector is not None:
        matches = [component for component in nodes if _matches(component, graph, selector)]
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise PnpmSbomError(f"Component selector '{selector}' is ambiguous for pnpm SBOM generation: {choices}")
        if not matches:
            return []
        plan = _plan_for_component(graph, matches[0], format, selected=True)
        return [plan] if plan is not None else []

    unique: dict[Path, PnpmSbomPlan] = {}
    for component in nodes:
        plan = _plan_for_component(graph, component, format, selected=False)
        if plan is not None:
            unique.setdefault(plan.cwd.resolve(), plan)
    return [unique[path] for path in sorted(unique, key=str)]


def parse_pnpm_sbom_output(text: str, plan: PnpmSbomPlan) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        raise PnpmSbomError("pnpm sbom produced no JSON output.")
    if plan.split:
        documents: list[dict[str, Any]] = []
        for line_number, line in enumerate(stripped.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PnpmSbomError(f"Could not parse pnpm split SBOM line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise PnpmSbomError(f"pnpm split SBOM line {line_number} is not a JSON object.")
            documents.append(value)
        if not documents:
            raise PnpmSbomError("pnpm split SBOM produced no documents.")
        return documents
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PnpmSbomError(f"Could not parse pnpm SBOM JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PnpmSbomError("pnpm SBOM JSON root is not an object.")
    return [value]


def execute_pnpm_sbom(
    plan: PnpmSbomPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> PnpmSbomResult:
    executable = which("pnpm")
    if executable is None:
        return PnpmSbomResult(plan, [], 127, "Executable 'pnpm' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return PnpmSbomResult(plan, [], 127, str(exc))
    if completed.returncode != 0:
        return PnpmSbomResult(plan, [], completed.returncode, (completed.stderr or "").strip())
    try:
        documents = parse_pnpm_sbom_output(completed.stdout or "", plan)
    except PnpmSbomError as exc:
        return PnpmSbomResult(plan, [], 1, str(exc))
    return PnpmSbomResult(plan, documents, 0, (completed.stderr or "").strip())


def stable_native_ref(component: str, document_index: int, native_ref: str, name: str, version: str | None) -> str:
    identity = "\0".join((component, str(document_index), native_ref, name, version or ""))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"urn:upm:pnpm-native:sha256:{digest}"
