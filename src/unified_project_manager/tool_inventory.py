from __future__ import annotations

import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from .models import ProjectGraph


@dataclass(frozen=True)
class ToolResolution:
    component: str
    role: str
    name: str
    requirement: str | None
    command: tuple[str, ...]
    resolved_path: str | None
    available: bool
    version: str | None
    version_returncode: int | None
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = list(self.command)
        return data


@dataclass(frozen=True)
class ToolRequirementDivergence:
    role: str
    name: str
    requirements: tuple[str, ...]
    components: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolInventory:
    resolutions: tuple[ToolResolution, ...]
    divergences: tuple[ToolRequirementDivergence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolutions": [item.to_dict() for item in self.resolutions],
            "divergences": [item.to_dict() for item in self.divergences],
            "network_executed": False,
            "mutation_executed": False,
        }


_MANAGER_VERSION_COMMANDS: dict[str, tuple[str, ...]] = {
    "npm": ("npm", "--version"),
    "pnpm": ("pnpm", "--version"),
    "yarn": ("yarn", "--version"),
    "bun": ("bun", "--version"),
    "uv": ("uv", "--version"),
    "poetry": ("poetry", "--version"),
    "pdm": ("pdm", "--version"),
    "pip": ("python", "-m", "pip", "--version"),
    "cargo": ("cargo", "--version"),
    "go": ("go", "version"),
}

_TOOLCHAIN_VERSION_COMMANDS: dict[str, tuple[str, ...]] = {
    "node": ("node", "--version"),
    "python": ("python", "--version"),
    "rust": ("rustc", "--version"),
    "rustc": ("rustc", "--version"),
    "go": ("go", "version"),
}


def _manager_requirement(manager: str, metadata: dict[str, Any]) -> str | None:
    declared = metadata.get("package_manager_declared")
    if not isinstance(declared, str):
        return None
    prefix = f"{manager}@"
    if declared.startswith(prefix):
        value = declared[len(prefix):].strip()
        return value or None
    return None


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def collect_tool_inventory(
    graph: ProjectGraph,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ToolInventory:
    requests: list[tuple[str, str, str, str | None, tuple[str, ...]]] = []
    for component in graph.components:
        key = component.key(graph.root)
        if component.manager:
            command = _MANAGER_VERSION_COMMANDS.get(component.manager)
            if command is not None:
                requests.append((
                    key,
                    "manager",
                    component.manager,
                    _manager_requirement(component.manager, component.metadata),
                    command,
                ))
        for toolchain in component.toolchains:
            command = _TOOLCHAIN_VERSION_COMMANDS.get(toolchain.name)
            if command is None:
                continue
            requests.append((
                key,
                "toolchain",
                toolchain.name,
                toolchain.requirement,
                command,
            ))

    command_cache: dict[tuple[str, ...], tuple[str | None, int | None, str | None, str]] = {}
    resolutions: list[ToolResolution] = []
    requirement_groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)

    for component, role, name, requirement, command in requests:
        if requirement:
            requirement_groups[(role, name)].append((component, requirement))
        if command not in command_cache:
            executable = which(command[0])
            if executable is None:
                command_cache[command] = (None, None, None, "")
            else:
                argv = [executable, *command[1:]]
                try:
                    completed = run(
                        argv,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                except OSError as exc:
                    command_cache[command] = (executable, 127, None, str(exc))
                else:
                    version = _first_line(completed.stdout or completed.stderr or "")
                    command_cache[command] = (
                        executable,
                        completed.returncode,
                        version,
                        completed.stderr or "",
                    )

        resolved_path, returncode, version, stderr = command_cache[command]
        resolutions.append(ToolResolution(
            component=component,
            role=role,
            name=name,
            requirement=requirement,
            command=command,
            resolved_path=resolved_path,
            available=resolved_path is not None and returncode != 127,
            version=version,
            version_returncode=returncode,
            stderr=stderr,
        ))

    divergences: list[ToolRequirementDivergence] = []
    for (role, name), values in sorted(requirement_groups.items()):
        requirements = tuple(sorted({requirement for _component, requirement in values}))
        if len(requirements) <= 1:
            continue
        divergences.append(ToolRequirementDivergence(
            role=role,
            name=name,
            requirements=requirements,
            components=tuple(sorted({component for component, _requirement in values})),
        ))

    resolutions.sort(key=lambda item: (item.role, item.name, item.component))
    return ToolInventory(tuple(resolutions), tuple(divergences))
