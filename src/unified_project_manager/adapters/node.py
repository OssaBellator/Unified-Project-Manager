from __future__ import annotations

import json
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ToolchainRequirement
from .base import Adapter

LOCKFILE_MANAGERS = {
    "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bun",
    "bun.lockb": "bun", "package-lock.json": "npm", "npm-shrinkwrap.json": "npm",
}
SUPPORTED_MANAGERS = frozenset(LOCKFILE_MANAGERS.values())


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
            if isinstance(data.get("name"), str):
                metadata["name"] = data["name"]
            if isinstance(data.get("version"), str):
                metadata["version"] = data["version"]

            package_manager = data.get("packageManager")
            legacy_manager: str | None = None
            if isinstance(package_manager, str) and package_manager:
                legacy_manager = package_manager.split("@", 1)[0]
                metadata["package_manager_declared"] = package_manager

            dev_manager: str | None = None
            dev_manager_version: str | None = None
            dev_engines = data.get("devEngines")
            if isinstance(dev_engines, dict):
                dev_package_manager = dev_engines.get("packageManager")
                if isinstance(dev_package_manager, dict) and isinstance(dev_package_manager.get("name"), str):
                    dev_manager = dev_package_manager["name"]
                    if isinstance(dev_package_manager.get("version"), str):
                        dev_manager_version = dev_package_manager["version"]
                    metadata["dev_engines_package_manager"] = dict(dev_package_manager)

            if legacy_manager and dev_manager and legacy_manager != dev_manager:
                metadata["manager_declarations"] = [legacy_manager, dev_manager]
                manager_from_manifest = legacy_manager
            elif legacy_manager:
                manager_from_manifest = legacy_manager
            elif dev_manager:
                manager_from_manifest = dev_manager
                metadata["package_manager_declared"] = f"{dev_manager}@{dev_manager_version}" if dev_manager_version else dev_manager

            engines = data.get("engines")
            if isinstance(engines, dict) and isinstance(engines.get("node"), str):
                toolchains.append(ToolchainRequirement("node", engines["node"]))
            else:
                toolchains.append(ToolchainRequirement("node"))

            sections = (
                ("dependencies", "runtime"),
                ("devDependencies", "development"),
                ("optionalDependencies", "optional"),
                ("peerDependencies", "peer"),
            )
            for section, scope in sections:
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
        metadata["manager_supported"] = manager in SUPPORTED_MANAGERS if manager else False

        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager=manager,
            manifests=["package.json"],
            lockfiles=lockfiles,
            toolchains=toolchains,
            dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name.lower())),
            metadata=metadata,
        )
