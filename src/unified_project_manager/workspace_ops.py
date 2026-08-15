from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .go_workspace import execute_workspace_inspection, plan_workspace_inspection
from .models import ProjectGraph


class WorkspaceOperationError(ValueError):
    """Raised when a workspace mutation cannot be planned or executed safely."""


@dataclass(frozen=True)
class WorkspaceSyncPlan:
    workspace: str
    cwd: Path
    argv: tuple[str, ...]
    tracked_files: tuple[Path, ...]
    external_members: tuple[Path, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        def render(path: Path) -> str:
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                return str(path)

        return {
            "workspace": self.workspace,
            "cwd": render(self.cwd),
            "argv": list(self.argv),
            "tracked_files": [render(path) for path in self.tracked_files],
            "external_members": [str(path) for path in self.external_members],
        }


@dataclass
class WorkspaceSyncResult:
    plan: WorkspaceSyncPlan
    executed: bool
    returncode: int | None = None
    changed_files: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.executed and self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "executed": self.executed,
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "changed_files": list(self.changed_files),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_workspace_sync(
    graph: ProjectGraph,
    selector: str | None = None,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> WorkspaceSyncPlan:
    inspection_plan = plan_workspace_inspection(graph, selector)
    inspection = execute_workspace_inspection(graph, inspection_plan, run=run, which=which)
    if not inspection.succeeded:
        raise WorkspaceOperationError(f"Could not inspect workspace before sync: {inspection.stderr}")

    tracked = {inspection_plan.manifest, inspection_plan.cwd / "go.work.sum"}
    external_members: list[Path] = []
    for use in inspection.uses or []:
        member = Path(use.resolved_path)
        tracked.add(member / "go.mod")
        tracked.add(member / "go.sum")
        if not use.in_project:
            external_members.append(member)

    return WorkspaceSyncPlan(
        workspace=inspection_plan.workspace,
        cwd=inspection_plan.cwd,
        argv=("go", "work", "sync"),
        tracked_files=tuple(sorted(tracked, key=str)),
        external_members=tuple(sorted(external_members, key=str)),
    )


def execute_workspace_sync(
    plan: WorkspaceSyncPlan,
    root: Path,
    *,
    allow_external: bool = False,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> WorkspaceSyncResult:
    if plan.external_members and not allow_external:
        members = ", ".join(str(path) for path in plan.external_members)
        raise WorkspaceOperationError(
            f"Workspace sync would modify external member(s): {members}. "
            "Re-run with --allow-external after reviewing the plan."
        )

    executable = which("go")
    if executable is None:
        return WorkspaceSyncResult(plan, True, 127, stderr="Executable 'go' is not available on PATH.")

    before = {path: _digest(path) for path in plan.tracked_files}
    environment = dict(os.environ)
    environment["GOWORK"] = str(plan.cwd / "go.work")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        return WorkspaceSyncResult(plan, True, 127, stderr=str(exc))

    after = {path: _digest(path) for path in plan.tracked_files}
    changed: list[str] = []
    for path in plan.tracked_files:
        if before[path] == after[path]:
            continue
        try:
            changed.append(path.relative_to(root).as_posix())
        except ValueError:
            changed.append(str(path))

    return WorkspaceSyncResult(
        plan=plan,
        executed=True,
        returncode=completed.returncode,
        changed_files=tuple(sorted(changed)),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
