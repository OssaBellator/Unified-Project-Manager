from __future__ import annotations

import tomllib
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter


def _render_requirement(requirement: object) -> str | None:
    if isinstance(requirement, str): return requirement
    if isinstance(requirement, dict) and isinstance(requirement.get("version"), str): return requirement["version"]
    return None


class RustAdapter(Adapter):
    ecosystem = "rust"

    def detect(self, directory: Path) -> bool:
        return (directory / "Cargo.toml").is_file()

    def inspect(self, directory: Path) -> Component:
        cargo_toml = directory / "Cargo.toml"
        metadata: dict[str, object] = {}
        dependencies: list[Dependency] = []
        toolchains = [ToolchainRequirement("rust")]

        try:
            data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
            package = data.get("package", {})
            if isinstance(package, dict):
                if isinstance(package.get("name"), str): metadata["name"] = package["name"]
                if isinstance(package.get("version"), str): metadata["version"] = package["version"]
                if isinstance(package.get("rust-version"), str): toolchains = [ToolchainRequirement("rust", package["rust-version"])]

            for section, scope in (("dependencies", "runtime"), ("dev-dependencies", "development"), ("build-dependencies", "build")):
                values = data.get(section, {})
                if isinstance(values, dict):
                    for name, requirement in values.items(): dependencies.append(Dependency(str(name), _render_requirement(requirement), scope))

            workspace = data.get("workspace")
            if isinstance(workspace, dict):
                metadata["workspace"] = True
                values = workspace.get("dependencies")
                if isinstance(values, dict):
                    for name, requirement in values.items(): dependencies.append(Dependency(str(name), _render_requirement(requirement), "workspace"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            metadata["parse_error"] = str(exc)

        if (directory / "Cargo.lock").is_file():
            try:
                tomllib.loads((directory / "Cargo.lock").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                metadata["lockfile_parse_errors"] = [f"Cargo.lock: {exc}"]

        return Component(ecosystem=self.ecosystem, path=directory, manager="cargo", manifests=["Cargo.toml"], lockfiles=["Cargo.lock"] if (directory / "Cargo.lock").is_file() else [], toolchains=toolchains, dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name.lower())), metadata=metadata)
