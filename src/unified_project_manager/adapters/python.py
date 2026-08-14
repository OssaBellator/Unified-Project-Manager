from __future__ import annotations

import re
import tomllib
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter


PYTHON_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class PythonAdapter(Adapter):
    ecosystem = "python"

    def detect(self, directory: Path) -> bool:
        return (directory / "pyproject.toml").is_file() or any(directory.glob("requirements*.txt"))

    def inspect(self, directory: Path) -> Component:
        pyproject = directory / "pyproject.toml"
        requirement_files = sorted(path.name for path in directory.glob("requirements*.txt") if path.is_file())
        manifests = (["pyproject.toml"] if pyproject.is_file() else []) + requirement_files
        lockfiles = [name for name in ("uv.lock", "poetry.lock", "pdm.lock") if (directory / name).is_file()]
        metadata: dict[str, object] = {}
        dependencies: list[Dependency] = []
        toolchains = [ToolchainRequirement("python")]

        manager = None
        if (directory / "uv.lock").is_file():
            manager = "uv"
        elif (directory / "poetry.lock").is_file():
            manager = "poetry"
        elif (directory / "pdm.lock").is_file():
            manager = "pdm"
        elif requirement_files:
            manager = "pip"

        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project = data.get("project", {})
                if isinstance(project, dict):
                    requires_python = project.get("requires-python")
                    if isinstance(requires_python, str):
                        toolchains = [ToolchainRequirement("python", requires_python)]
                    values = project.get("dependencies", [])
                    if isinstance(values, list):
                        for value in values:
                            if not isinstance(value, str):
                                continue
                            match = PYTHON_NAME.match(value)
                            if match:
                                dependencies.append(Dependency(match.group(1), value, "runtime"))

                tool = data.get("tool", {})
                if isinstance(tool, dict):
                    if "uv" in tool and manager is None:
                        manager = "uv"
                    elif "poetry" in tool and manager is None:
                        manager = "poetry"
                    elif "pdm" in tool and manager is None:
                        manager = "pdm"
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                metadata["parse_error"] = str(exc)

        for requirements_name in requirement_files:
            try:
                for raw_line in (directory / requirements_name).read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith(("-r", "--")):
                        continue
                    match = PYTHON_NAME.match(line)
                    if match:
                        dependencies.append(Dependency(match.group(1), line, "runtime"))
            except (OSError, UnicodeDecodeError) as exc:
                metadata.setdefault("requirements_errors", []).append(f"{requirements_name}: {exc}")

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager=manager,
            manifests=manifests,
            lockfiles=lockfiles,
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: item.name.lower()),
            metadata=metadata,
        )
