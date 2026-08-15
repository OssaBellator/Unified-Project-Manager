from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import ProjectGraph


@dataclass(frozen=True)
class EnvironmentObservation:
    variable: str
    kind: str
    value: str
    path: str | None
    in_project: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentFinding:
    code: str
    severity: str
    message: str
    variable: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentInspection:
    observations: tuple[EnvironmentObservation, ...]
    findings: tuple[EnvironmentFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "findings": [item.to_dict() for item in self.findings],
            "network_executed": False,
            "mutation_executed": False,
        }


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _path_observation(root: Path, variable: str, kind: str, value: str) -> EnvironmentObservation:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve()
        rendered = str(resolved)
        inside = _inside(root, resolved)
    except OSError:
        rendered = str(path)
        inside = False
    return EnvironmentObservation(variable, kind, value, rendered, inside)


def _path_list(
    root: Path,
    variable: str,
    kind: str,
    value: str,
) -> list[EnvironmentObservation]:
    observations: list[EnvironmentObservation] = []
    for raw in value.split(os.pathsep):
        if not raw:
            continue
        observations.append(_path_observation(root, variable, kind, raw))
    return observations


def inspect_environment(
    graph: ProjectGraph,
    *,
    environ: Mapping[str, str] | None = None,
) -> EnvironmentInspection:
    env = os.environ if environ is None else environ
    root = graph.root
    ecosystems = {component.ecosystem for component in graph.components}
    observations: list[EnvironmentObservation] = []
    findings: list[EnvironmentFinding] = []

    if "python" in ecosystems:
        for variable, kind, code in (
            ("VIRTUAL_ENV", "python-environment", "environment.python.external-virtualenv"),
            ("CONDA_PREFIX", "python-environment", "environment.python.external-conda"),
        ):
            value = env.get(variable)
            if not value:
                continue
            observation = _path_observation(root, variable, kind, value)
            observations.append(observation)
            if observation.in_project is False:
                findings.append(EnvironmentFinding(
                    code,
                    "warning",
                    f"{variable} points outside the selected project; Python commands may observe a different environment than the project-local state.",
                    variable,
                    observation.path,
                ))

        value = env.get("PYTHONPATH")
        if value:
            for observation in _path_list(root, "PYTHONPATH", "python-import-path", value):
                observations.append(observation)
                if observation.in_project is False:
                    findings.append(EnvironmentFinding(
                        "environment.python.external-pythonpath",
                        "warning",
                        "PYTHONPATH contains an entry outside the selected project; imports may resolve from external source trees.",
                        "PYTHONPATH",
                        observation.path,
                    ))

    if "node" in ecosystems:
        value = env.get("NODE_PATH")
        if value:
            for observation in _path_list(root, "NODE_PATH", "node-module-path", value):
                observations.append(observation)
                if observation.in_project is False:
                    findings.append(EnvironmentFinding(
                        "environment.node.external-node-path",
                        "warning",
                        "NODE_PATH contains an entry outside the selected project; Node module resolution may observe external modules.",
                        "NODE_PATH",
                        observation.path,
                    ))

    if "go" in ecosystems:
        gowork = env.get("GOWORK")
        if gowork and gowork.lower() not in {"off", "auto"}:
            observation = _path_observation(root, "GOWORK", "go-workspace", gowork)
            observations.append(observation)
            if observation.in_project is False:
                findings.append(EnvironmentFinding(
                    "environment.go.external-workspace",
                    "warning",
                    "GOWORK explicitly selects a workspace outside the project; generic Go commands may see different module membership than UPM component-scoped operations.",
                    "GOWORK",
                    observation.path,
                ))
        elif gowork:
            observations.append(EnvironmentObservation("GOWORK", "go-workspace-mode", gowork, None, None))

    # Shared/global locations are useful context but are not classified as
    # project leakage merely because they are outside the repository.
    for variable, kind in (
        ("GOMODCACHE", "shared-cache"),
        ("GOPATH", "shared-tool-home"),
        ("CARGO_HOME", "shared-tool-home"),
        ("npm_config_prefix", "shared-tool-prefix"),
    ):
        value = env.get(variable)
        if value:
            observations.append(_path_observation(root, variable, kind, value))

    observations.sort(key=lambda item: (item.variable, item.path or "", item.value))
    findings.sort(key=lambda item: (item.severity, item.code, item.variable, item.path or ""))
    return EnvironmentInspection(tuple(observations), tuple(findings))
