from __future__ import annotations

import tomllib
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter


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
            if isinstance(package, dict) and isinstance(package.get("rust-version"), str):
                toolchains = [ToolchainRequirement("rust", package["rust-version"])]

            for section, scope in (("dependencies", "runtime"), ("dev-dependencies", "development"), ("build-dependencies", "build")):
                values = data.get(section, {})
                if not isinstance(values, dict):
                    continue
                for name, requirement in values.items():
                    rendered = requirement if isinstance(requirement, str) else None
                    if isinstance(requirement, dict) and isinstance(requirement.get("version"), str):
                        rendered = requirement["version"]
                    dependencies.append(Dependency(str(name), rendered, scope))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            metadata["parse_error"] = str(exc)

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager="cargo",
            manifests=["Cargo.toml"],
            lockfiles=["Cargo.lock"] if (directory / "Cargo.lock").is_file() else [],
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name)),
            metadata=metadata,
        )
