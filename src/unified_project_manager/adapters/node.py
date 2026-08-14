from __future__ import annotations

import json
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter


LOCKFILE_MANAGERS = {
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
}


class NodeAdapter(Adapter):
    ecosystem = "node"

    def detect(self, directory: Path) -> bool:
        return (directory / "package.json").is_file()

    def inspect(self, directory: Path) -> Component:
        package_json = directory / "package.json"
        lockfiles = [name for name in LOCKFILE_MANAGERS if (directory / name).is_file()]
        manager_from_lock = LOCKFILE_MANAGERS[lockfiles[0]] if len(lockfiles) == 1 else None
        metadata: dict[str, object] = {}
        dependencies: list[Dependency] = []
        toolchains: list[ToolchainRequirement] = []
        manager_from_manifest: str | None = None

        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            package_manager = data.get("packageManager")
            if isinstance(package_manager, str) and package_manager:
                manager_from_manifest = package_manager.split("@", 1)[0]
                metadata["package_manager_declared"] = package_manager

            engines = data.get("engines")
            if isinstance(engines, dict) and isinstance(engines.get("node"), str):
                toolchains.append(ToolchainRequirement("node", engines["node"]))
            else:
                toolchains.append(ToolchainRequirement("node"))

            for section, scope in (("dependencies", "runtime"), ("devDependencies", "development"), ("optionalDependencies", "optional")):
                values = data.get(section)
                if not isinstance(values, dict):
                    continue
                for name, requirement in values.items():
                    if isinstance(name, str):
                        dependencies.append(Dependency(name, str(requirement), scope))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            metadata["parse_error"] = str(exc)
            toolchains.append(ToolchainRequirement("node"))

        manager = manager_from_manifest or manager_from_lock
        metadata["manager_from_lock"] = manager_from_lock
        metadata["manager_from_manifest"] = manager_from_manifest

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager=manager,
            manifests=["package.json"],
            lockfiles=lockfiles,
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name)),
            metadata=metadata,
        )
