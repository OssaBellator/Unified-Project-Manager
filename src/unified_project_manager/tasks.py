from __future__ import annotations

import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TaskError(ValueError):
    """Raised when UPM task configuration or task planning is invalid."""


@dataclass(frozen=True)
class TaskSpec:
    name: str
    argv: tuple[str, ...]
    cwd: Path
    description: str | None = None
    depends: tuple[str, ...] = ()

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "name": self.name,
            "argv": list(self.argv),
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "description": self.description,
            "depends": list(self.depends),
        }


@dataclass
class TaskResult:
    task: TaskSpec
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(root),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def _inside(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def load_tasks(root: str | Path) -> dict[str, TaskSpec]:
    root_path = Path(root).expanduser().resolve()
    config_path = root_path / "upm.toml"
    if not config_path.is_file():
        return {}
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise TaskError(f"Could not read {config_path}: {exc}") from exc
    tasks_value = data.get("tasks")
    if tasks_value is None:
        return {}
    if not isinstance(tasks_value, dict):
        raise TaskError("upm.toml [tasks] must be a table.")

    tasks: dict[str, TaskSpec] = {}
    for name, value in tasks_value.items():
        if not isinstance(name, str) or not name:
            raise TaskError("Task names must be non-empty strings.")
        if not isinstance(value, dict):
            raise TaskError(f"Task '{name}' must be a table.")
        command = value.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise TaskError(f"Task '{name}' command must be a non-empty array of strings; shell command strings are intentionally unsupported.")
        cwd_value = value.get("cwd", ".")
        if not isinstance(cwd_value, str):
            raise TaskError(f"Task '{name}' cwd must be a string.")
        cwd = (root_path / cwd_value).resolve()
        if not _inside(root_path, cwd):
            raise TaskError(f"Task '{name}' cwd escapes the project root: {cwd_value}")
        description = value.get("description")
        if description is not None and not isinstance(description, str):
            raise TaskError(f"Task '{name}' description must be a string.")
        depends_value = value.get("depends", [])
        if not isinstance(depends_value, list) or not all(isinstance(item, str) and item for item in depends_value):
            raise TaskError(f"Task '{name}' depends must be an array of task names.")
        tasks[name] = TaskSpec(name, tuple(command), cwd, description, tuple(depends_value))

    for task in tasks.values():
        missing = [dependency for dependency in task.depends if dependency not in tasks]
        if missing:
            raise TaskError(f"Task '{task.name}' depends on unknown task(s): {', '.join(missing)}")
    return tasks


def plan_task(root: str | Path, name: str) -> list[TaskSpec]:
    tasks = load_tasks(root)
    if name not in tasks:
        raise TaskError(f"Unknown task '{name}'." if tasks else "No UPM tasks are configured in upm.toml.")

    ordered: list[TaskSpec] = []
    complete: set[str] = set()
    visiting: list[str] = []

    def visit(task_name: str) -> None:
        if task_name in complete:
            return
        if task_name in visiting:
            cycle = " -> ".join([*visiting[visiting.index(task_name):], task_name])
            raise TaskError(f"Task dependency cycle detected: {cycle}")
        visiting.append(task_name)
        task = tasks[task_name]
        for dependency in task.depends:
            visit(dependency)
        visiting.pop()
        complete.add(task_name)
        ordered.append(task)

    visit(name)
    return ordered


def execute_task(
    task: TaskSpec,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> TaskResult:
    executable = task.argv[0]
    if which(executable) is None:
        return TaskResult(task, 127, stderr=f"Executable '{executable}' is not available on PATH.")
    try:
        completed = run(list(task.argv), cwd=task.cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return TaskResult(task, 127, stderr=str(exc))
    return TaskResult(task, completed.returncode, completed.stdout or "", completed.stderr or "")
