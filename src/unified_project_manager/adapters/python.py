from __future__ import annotations

import re
import tomllib
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ResolvedPackage, ToolchainRequirement
from .base import Adapter

PYTHON_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _dependency(value: object, scope: str) -> Dependency | None:
    if not isinstance(value, str):
        return None
    match = PYTHON_NAME.match(value)
    return Dependency(match.group(1), value, scope) if match else None


def _append_list(target: list[Dependency], values: object, scope: str) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        dependency = _dependency(value, scope)
        if dependency:
            target.append(dependency)


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
        resolved_packages: list[ResolvedPackage] = []
        toolchains = [ToolchainRequirement("python")]

        lockfile_managers = {"uv.lock": "uv", "poetry.lock": "poetry", "pdm.lock": "pdm"}
        manager_from_lock = lockfile_managers[lockfiles[0]] if len(lockfiles) == 1 else None
        manager_from_manifest: str | None = None

        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project = data.get("project", {})
                if isinstance(project, dict):
                    if isinstance(project.get("name"), str): metadata["name"] = project["name"]
                    if isinstance(project.get("version"), str): metadata["version"] = project["version"]
                    requires_python = project.get("requires-python")
                    if isinstance(requires_python, str):
                        toolchains = [ToolchainRequirement("python", requires_python)]
                    _append_list(dependencies, project.get("dependencies"), "runtime")
                    optional = project.get("optional-dependencies")
                    if isinstance(optional, dict):
                        for group, values in optional.items():
                            _append_list(dependencies, values, f"optional:{group}")

                groups = data.get("dependency-groups")
                if isinstance(groups, dict):
                    for group, values in groups.items():
                        _append_list(dependencies, values, f"development:{group}")

                tool = data.get("tool", {})
                if isinstance(tool, dict):
                    declared_managers = [name for name in ("uv", "poetry", "pdm") if name in tool]
                    if len(declared_managers) == 1:
                        manager_from_manifest = declared_managers[0]
                    elif len(declared_managers) > 1:
                        metadata["manager_declarations"] = declared_managers

                    poetry = tool.get("poetry")
                    if isinstance(poetry, dict):
                        poetry_deps = poetry.get("dependencies")
                        if isinstance(poetry_deps, dict):
                            for name, requirement in poetry_deps.items():
                                if str(name).lower() == "python":
                                    if isinstance(requirement, str) and toolchains[0].requirement is None:
                                        toolchains = [ToolchainRequirement("python", requirement)]
                                    continue
                                rendered = requirement if isinstance(requirement, str) else None
                                dependencies.append(Dependency(str(name), rendered, "runtime"))
                        poetry_groups = poetry.get("group")
                        if isinstance(poetry_groups, dict):
                            for group, group_data in poetry_groups.items():
                                if not isinstance(group_data, dict):
                                    continue
                                group_deps = group_data.get("dependencies")
                                if not isinstance(group_deps, dict):
                                    continue
                                for name, requirement in group_deps.items():
                                    rendered = requirement if isinstance(requirement, str) else None
                                    dependencies.append(Dependency(str(name), rendered, f"development:{group}"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                metadata["parse_error"] = str(exc)

        lockfile_parse_errors: list[str] = []
        for lockfile_name in lockfiles:
            try:
                lock_data = tomllib.loads((directory / lockfile_name).read_text(encoding="utf-8"))
                packages = lock_data.get("package")
                if isinstance(packages, list):
                    for record in packages:
                        if not isinstance(record, dict):
                            continue
                        name = record.get("name")
                        version = record.get("version")
                        if isinstance(name, str) and isinstance(version, str):
                            source = record.get("source")
                            rendered_source = str(source) if source is not None else None
                            resolved_packages.append(ResolvedPackage(name=name, version=version, source=rendered_source, location=lockfile_name))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                lockfile_parse_errors.append(f"{lockfile_name}: {exc}")
        if lockfile_parse_errors:
            metadata["lockfile_parse_errors"] = lockfile_parse_errors

        manager = manager_from_manifest or manager_from_lock or ("pip" if requirement_files else None)
        metadata["manager_from_lock"] = manager_from_lock
        metadata["manager_from_manifest"] = manager_from_manifest

        for requirements_name in requirement_files:
            try:
                for raw_line in (directory / requirements_name).read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or line.startswith(("-r", "--")):
                        continue
                    dependency = _dependency(line, f"requirements:{requirements_name}")
                    if dependency:
                        dependencies.append(dependency)
            except (OSError, UnicodeDecodeError) as exc:
                metadata.setdefault("requirements_errors", []).append(f"{requirements_name}: {exc}")

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager=manager,
            manifests=manifests,
            lockfiles=lockfiles,
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: (item.name.lower(), item.scope)),
            resolved_packages=sorted(resolved_packages, key=lambda item: (item.name.lower(), item.version, item.location or "")),
            metadata=metadata,
        )
