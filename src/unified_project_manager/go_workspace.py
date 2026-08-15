from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ProjectGraph, Workspace


class WorkspaceError(ValueError):
    """Raised when a workspace cannot be selected or inspected safely."""


@dataclass(frozen=True)
class WorkspaceInspectionPlan:
    workspace: str
    ecosystem: str
    manager: str
    cwd: Path
    manifest: Path
    argv: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "ecosystem": self.ecosystem,
            "manager": self.manager,
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "manifest": self.manifest.relative_to(root).as_posix(),
            "argv": list(self.argv),
        }


@dataclass(frozen=True)
class WorkspaceUse:
    disk_path: str
    module_path: str | None
    resolved_path: str
    in_project: bool
    component: str | None
    exists: bool
    has_go_mod: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceReplace:
    old_path: str
    old_version: str | None
    new_path: str
    new_version: str | None
    local: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceInspectionResult:
    plan: WorkspaceInspectionPlan
    returncode: int
    go_version: str | None = None
    toolchain: str | None = None
    uses: list[WorkspaceUse] | None = None
    replacements: list[WorkspaceReplace] | None = None
    godebug: list[dict[str, str]] | None = None
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "go_version": self.go_version,
            "toolchain": self.toolchain,
            "uses": [item.to_dict() for item in self.uses or []],
            "replacements": [item.to_dict() for item in self.replacements or []],
            "godebug": self.godebug or [],
            "stderr": self.stderr,
        }


def _select_workspace(graph: ProjectGraph, selector: str | None) -> Workspace:
    candidates = [workspace for workspace in graph.workspaces if workspace.ecosystem == "go"]
    if selector is not None:
        candidates = [workspace for workspace in candidates if selector in {
            workspace.key(graph.root),
            workspace.relative_path(graph.root),
            workspace.ecosystem,
        }]
    if not candidates:
        raise WorkspaceError("No matching Go workspace was discovered.")
    if len(candidates) > 1:
        choices = ", ".join(workspace.key(graph.root) for workspace in candidates)
        raise WorkspaceError(f"Workspace selector is ambiguous: {choices}")
    return candidates[0]


def plan_workspace_inspection(graph: ProjectGraph, selector: str | None = None) -> WorkspaceInspectionPlan:
    workspace = _select_workspace(graph, selector)
    manifest = workspace.path / "go.work"
    return WorkspaceInspectionPlan(
        workspace=workspace.key(graph.root),
        ecosystem="go",
        manager="go",
        cwd=workspace.path,
        manifest=manifest,
        argv=("go", "work", "edit", "-json", str(manifest)),
    )


def _module(value: object) -> tuple[str, str | None]:
    if not isinstance(value, dict):
        return "", None
    path = value.get("Path")
    version = value.get("Version")
    return (
        path if isinstance(path, str) else "",
        version if isinstance(version, str) and version else None,
    )


def parse_workspace_json(
    graph: ProjectGraph,
    plan: WorkspaceInspectionPlan,
    text: str,
) -> WorkspaceInspectionResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Could not parse go work edit JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError("go work edit JSON root is not an object.")

    components_by_path = {
        component.path.resolve(): component.key(graph.root)
        for component in graph.components
        if component.ecosystem == "go"
    }
    uses: list[WorkspaceUse] = []
    for item in data.get("Use") or []:
        if not isinstance(item, dict) or not isinstance(item.get("DiskPath"), str):
            continue
        disk_path = item["DiskPath"]
        path = Path(disk_path).expanduser()
        if not path.is_absolute():
            path = plan.cwd / path
        path = path.resolve()
        try:
            path.relative_to(graph.root)
            in_project = True
        except ValueError:
            in_project = False
        uses.append(WorkspaceUse(
            disk_path=disk_path,
            module_path=item.get("ModulePath") if isinstance(item.get("ModulePath"), str) and item.get("ModulePath") else None,
            resolved_path=str(path),
            in_project=in_project,
            component=components_by_path.get(path),
            exists=path.is_dir(),
            has_go_mod=(path / "go.mod").is_file(),
        ))

    replacements: list[WorkspaceReplace] = []
    for item in data.get("Replace") or []:
        if not isinstance(item, dict):
            continue
        old_path, old_version = _module(item.get("Old"))
        new_path, new_version = _module(item.get("New"))
        if not old_path or not new_path:
            continue
        replacements.append(WorkspaceReplace(
            old_path=old_path,
            old_version=old_version,
            new_path=new_path,
            new_version=new_version,
            local=new_version is None,
        ))

    godebug: list[dict[str, str]] = []
    for item in data.get("Godebug") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("Key")
        value = item.get("Value")
        if isinstance(key, str) and isinstance(value, str):
            godebug.append({"key": key, "value": value})

    return WorkspaceInspectionResult(
        plan=plan,
        returncode=0,
        go_version=data.get("Go") if isinstance(data.get("Go"), str) else None,
        toolchain=data.get("Toolchain") if isinstance(data.get("Toolchain"), str) else None,
        uses=uses,
        replacements=replacements,
        godebug=godebug,
    )


def execute_workspace_inspection(
    graph: ProjectGraph,
    plan: WorkspaceInspectionPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> WorkspaceInspectionResult:
    executable = which("go")
    if executable is None:
        return WorkspaceInspectionResult(plan, 127, stderr="Executable 'go' is not available on PATH.")

    environment = dict(os.environ)
    environment["GOWORK"] = "off"
    argv = [executable, *plan.argv[1:]]
    try:
        completed = run(
            argv,
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        return WorkspaceInspectionResult(plan, 127, stderr=str(exc))
    if completed.returncode != 0:
        return WorkspaceInspectionResult(
            plan,
            completed.returncode,
            stderr=(completed.stderr or completed.stdout or "").strip(),
        )
    try:
        return parse_workspace_json(graph, plan, completed.stdout or "")
    except WorkspaceError as exc:
        return WorkspaceInspectionResult(plan, 1, stderr=str(exc))
