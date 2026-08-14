from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .models import CommandPlan, CommandResult


class InitializationError(ValueError):
    """Raised when UPM cannot safely plan native project initialization."""


DEFAULT_MANAGERS = {
    "node": "npm",
    "python": "uv",
    "rust": "cargo",
}
SUPPORTED_MANAGERS = {
    "node": {"npm", "pnpm", "bun"},
    "python": {"uv"},
    "rust": {"cargo"},
}


def _target_path(root: Path, target: str | Path) -> Path:
    root = root.expanduser().resolve()
    value = Path(target).expanduser()
    target_path = value.resolve() if value.is_absolute() else (root / value).resolve()
    if target_path != root and root not in target_path.parents:
        raise InitializationError("Initialization target must stay within the selected project root.")
    if target_path.exists() and not target_path.is_dir():
        raise InitializationError(f"Initialization target is not a directory: {target_path}")
    if target_path.is_dir() and any(target_path.iterdir()):
        raise InitializationError("Initialization target must be new or empty; refusing to modify an existing directory.")
    return target_path


def plan_initialization(
    root: str | Path,
    target: str | Path,
    ecosystem: str,
    manager: str | None = None,
    *,
    library: bool = False,
) -> CommandPlan:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise InitializationError(f"Project root is not a directory: {root_path}")
    if ecosystem not in DEFAULT_MANAGERS:
        raise InitializationError(f"Unsupported initialization ecosystem '{ecosystem}'.")

    selected_manager = manager or DEFAULT_MANAGERS[ecosystem]
    if selected_manager not in SUPPORTED_MANAGERS[ecosystem]:
        supported = ", ".join(sorted(SUPPORTED_MANAGERS[ecosystem]))
        raise InitializationError(f"Manager '{selected_manager}' cannot initialize {ecosystem} projects yet. Supported: {supported}.")

    target_path = _target_path(root_path, target)
    relative = target_path.relative_to(root_path)
    location = "." if str(relative) == "." else relative.as_posix()

    if ecosystem == "node":
        if library:
            raise InitializationError("--lib is not defined for the generic Node initializer.")
        if selected_manager == "npm":
            argv = ("npm", "init", "--yes")
        elif selected_manager == "pnpm":
            argv = ("pnpm", "init", "--bare", "--init-package-manager")
        else:
            argv = ("bun", "init", "--yes")
    elif ecosystem == "python":
        argv = ("uv", "init", *(("--lib",) if library else ()), ".")
    else:
        argv = ("cargo", "init", ".", "--vcs", "none", *(("--lib",) if library else ()))

    return CommandPlan(
        operation="init",
        component=f"{location}:{ecosystem}",
        manager=selected_manager,
        argv=argv,
        cwd=target_path,
    )


def execute_initialization(
    plan: CommandPlan,
    root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    verify: bool = True,
) -> CommandResult:
    executable = plan.argv[0]
    if which(executable) is None:
        return CommandResult(plan=plan, executed=True, returncode=127, stderr=f"Executable '{executable}' is not available on PATH.")

    try:
        plan.cwd.mkdir(parents=True, exist_ok=True)
        completed = run(list(plan.argv), cwd=plan.cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return CommandResult(plan=plan, executed=True, returncode=127, stderr=str(exc))

    result = CommandResult(
        plan=plan,
        executed=True,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if completed.returncode == 0 and verify:
        result.verification = diagnose(discover(root), which=which)
    return result
