from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .discovery import discover
from .doctor import diagnose
from .models import CommandPlan, CommandResult
from .package_planner import OperationError, plan_operation, plan_operations, select_component

__all__ = [
    "OperationError",
    "execute_plan",
    "plan_operation",
    "plan_operations",
    "render_command",
    "select_component",
]


def render_command(plan: CommandPlan) -> str:
    return shlex.join(plan.argv)


def execute_plan(
    plan: CommandPlan,
    root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    verify: bool = True,
) -> CommandResult:
    executable = plan.argv[0]
    resolved = which(executable)
    if resolved is None:
        return CommandResult(
            plan=plan,
            executed=True,
            returncode=127,
            stderr=f"Executable '{executable}' is not available on PATH.",
        )

    environment = None
    if plan.manager == "go":
        environment = dict(os.environ)
        environment["GOWORK"] = "off"

    kwargs = {
        "cwd": plan.cwd,
        "text": True,
        "capture_output": True,
        "check": False,
    }
    if environment is not None:
        kwargs["env"] = environment

    try:
        completed = run(
            [resolved, *plan.argv[1:]],
            **kwargs,
        )
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
