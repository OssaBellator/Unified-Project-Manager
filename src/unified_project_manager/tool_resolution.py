from __future__ import annotations

import os
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .models import ProjectGraph


@dataclass(frozen=True)
class ToolResolutionObservation:
    component: str
    role: str
    name: str
    requirement: str | None
    probe_command: tuple[str, ...]
    resolved_path: str | None
    available: bool
    version: str | None
    version_returncode: int | None
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["probe_command"] = list(self.probe_command)
        return data


@dataclass(frozen=True)
class ToolResolutionDivergence:
    role: str
    name: str
    requirements: tuple[str, ...]
    components: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResolutionReport:
    observations: tuple[ToolResolutionObservation, ...]
    divergences: tuple[ToolResolutionDivergence, ...]
    version_probes_executed: bool

    @property
    def network_guarantee(self) -> str:
        return "no-execution" if not self.version_probes_executed else "not-guaranteed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "divergences": [item.to_dict() for item in self.divergences],
            "version_probes_executed": self.version_probes_executed,
            "network_guarantee": self.network_guarantee,
            "network_executed": False if not self.version_probes_executed else None,
            "mutation_executed": False,
        }


_MANAGER_PROBES: dict[str, tuple[str, ...]] = {
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

_TOOLCHAIN_PROBES: dict[str, tuple[str, ...]] = {
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
    if not declared.startswith(prefix):
        return None
    value = declared[len(prefix):].strip()
    return value or None


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def _probe_environment(environ: Mapping[str, str] | None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    # This prevents Corepack itself from downloading managers during a probe.
    # It is a mitigation, not a universal offline guarantee: the resolved
    # executable can be another shim/tool-version manager with its own behavior.
    env["COREPACK_ENABLE_NETWORK"] = "0"
    return env


def collect_tool_resolution(
    graph: ProjectGraph,
    *,
    probe_versions: bool = False,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    environ: Mapping[str, str] | None = None,
) -> ToolResolutionReport:
    requests: list[tuple[str, str, str, str | None, tuple[str, ...]]] = []
    for component in graph.components:
        key = component.key(graph.root)
        if component.manager:
            command = _MANAGER_PROBES.get(component.manager)
            if command is not None:
                requests.append((
                    key,
                    "manager",
                    component.manager,
                    _manager_requirement(component.manager, component.metadata),
                    command,
                ))
        for toolchain in component.toolchains:
            command = _TOOLCHAIN_PROBES.get(toolchain.name)
            if command is not None:
                requests.append((
                    key,
                    "toolchain",
                    toolchain.name,
                    toolchain.requirement,
                    command,
                ))

    path_cache: dict[str, str | None] = {}
    probe_cache: dict[tuple[str, ...], tuple[int | None, str | None, str]] = {}
    observations: list[ToolResolutionObservation] = []
    requirement_groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    probe_env = _probe_environment(environ) if probe_versions else None

    for component, role, name, requirement, command in requests:
        if requirement:
            requirement_groups[(role, name)].append((component, requirement))
        executable_name = command[0]
        if executable_name not in path_cache:
            path_cache[executable_name] = which(executable_name)
        executable = path_cache[executable_name]

        returncode: int | None = None
        version: str | None = None
        stderr = ""
        if probe_versions and executable is not None:
            cache_key = (executable, *command[1:])
            if cache_key not in probe_cache:
                argv = [executable, *command[1:]]
                try:
                    completed = run(
                        argv,
                        text=True,
                        capture_output=True,
                        check=False,
                        env=probe_env,
                    )
                except OSError as exc:
                    probe_cache[cache_key] = (127, None, str(exc))
                else:
                    probe_cache[cache_key] = (
                        completed.returncode,
                        _first_line(completed.stdout or completed.stderr or ""),
                        completed.stderr or "",
                    )
            returncode, version, stderr = probe_cache[cache_key]

        observations.append(ToolResolutionObservation(
            component=component,
            role=role,
            name=name,
            requirement=requirement,
            probe_command=command,
            resolved_path=executable,
            available=executable is not None,
            version=version,
            version_returncode=returncode,
            stderr=stderr,
        ))

    divergences: list[ToolResolutionDivergence] = []
    for (role, name), values in sorted(requirement_groups.items()):
        requirements = tuple(sorted({requirement for _component, requirement in values}))
        if len(requirements) <= 1:
            continue
        divergences.append(ToolResolutionDivergence(
            role=role,
            name=name,
            requirements=requirements,
            components=tuple(sorted({component for component, _requirement in values})),
        ))

    observations.sort(key=lambda item: (item.role, item.name, item.component))
    return ToolResolutionReport(tuple(observations), tuple(divergences), probe_versions)
