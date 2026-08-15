from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class PnpmWorkspaceError(ValueError):
    """Raised when pnpm workspace inspection cannot be planned or parsed safely."""


@dataclass(frozen=True)
class PnpmWorkspacePlan:
    root: Path
    argv: tuple[str, ...] = ("pnpm", "list", "-r", "--depth", "-1", "--json")

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "argv": list(self.argv),
            "network": False,
            "mutates_project": False,
            "source": "pnpm-workspace.yaml via pnpm",
        }


@dataclass(frozen=True)
class PnpmWorkspaceMember:
    path: Path
    name: str | None
    version: str | None
    private: bool | None

    def to_dict(self, root: Path) -> dict[str, Any]:
        try:
            relative = self.path.relative_to(root).as_posix() or "."
        except ValueError:
            relative = str(self.path)
        return {"path": relative, "name": self.name, "version": self.version, "private": self.private}


@dataclass
class PnpmWorkspaceResult:
    plan: PnpmWorkspacePlan
    members: list[PnpmWorkspaceMember]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "members": [member.to_dict(self.plan.root) for member in self.members],
            "stderr": self.stderr,
        }


def find_pnpm_workspace_root(path: str | Path, boundary: str | Path | None = None) -> Path | None:
    current = Path(path).expanduser().resolve()
    if current.is_file():
        current = current.parent
    stop = Path(boundary).expanduser().resolve() if boundary is not None else None
    while True:
        if (current / "pnpm-workspace.yaml").is_file():
            return current
        if stop is not None and current == stop:
            return None
        parent = current.parent
        if parent == current:
            return None
        if stop is not None:
            try:
                parent.relative_to(stop)
            except ValueError:
                return None
        current = parent


def plan_pnpm_workspace(path: str | Path, boundary: str | Path | None = None) -> PnpmWorkspacePlan | None:
    root = find_pnpm_workspace_root(path, boundary)
    return PnpmWorkspacePlan(root) if root is not None else None


def parse_pnpm_workspace_list(text: str, root: Path) -> list[PnpmWorkspaceMember]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PnpmWorkspaceError(f"Could not parse pnpm workspace JSON: {exc}") from exc
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise PnpmWorkspaceError("pnpm workspace JSON must be an object or array.")

    members: list[PnpmWorkspaceMember] = []
    seen: set[Path] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        raw_path = record.get("path")
        if isinstance(raw_path, str) and raw_path:
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
        else:
            # Some pnpm JSON variants report the project as the current working directory.
            path = root
        if path in seen:
            continue
        seen.add(path)
        members.append(PnpmWorkspaceMember(
            path=path,
            name=record.get("name") if isinstance(record.get("name"), str) else None,
            version=record.get("version") if isinstance(record.get("version"), str) else None,
            private=record.get("private") if isinstance(record.get("private"), bool) else None,
        ))
    return sorted(members, key=lambda item: str(item.path))


def execute_pnpm_workspace(
    plan: PnpmWorkspacePlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> PnpmWorkspaceResult:
    executable = which("pnpm")
    if executable is None:
        return PnpmWorkspaceResult(plan, [], 127, stderr="Executable 'pnpm' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return PnpmWorkspaceResult(plan, [], 127, stderr=str(exc))
    if completed.returncode != 0:
        return PnpmWorkspaceResult(plan, [], completed.returncode, completed.stdout or "", completed.stderr or "")
    try:
        members = parse_pnpm_workspace_list(completed.stdout or "", plan.root)
    except PnpmWorkspaceError as exc:
        return PnpmWorkspaceResult(plan, [], 1, completed.stdout or "", str(exc))
    return PnpmWorkspaceResult(plan, members, 0, completed.stdout or "", completed.stderr or "")
