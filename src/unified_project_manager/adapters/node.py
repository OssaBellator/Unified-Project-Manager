from __future__ import annotations

import json
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ResolvedPackage, ToolchainRequirement
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
        resolved_packages: list[ResolvedPackage] = []
        toolchains: list[ToolchainRequirement] = []
        manager_from_manifest: str | None = None
        package_data: dict[str, object] | None = None

        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                package_data = data
            if isinstance(data.get("name"), str):
                metadata["name"] = data["name"]
            if isinstance(data.get("version"), str):
                metadata["version"] = data["version"]
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                metadata["scripts"] = {str(name): command for name, command in scripts.items() if isinstance(name, str) and isinstance(command, str)}

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

        lockfile_parse_errors: list[str] = []
        if len(lockfiles) == 1 and manager_from_lock == "npm":
            lockfile_name = lockfiles[0]
            try:
                lock_data = json.loads((directory / lockfile_name).read_text(encoding="utf-8"))
                if isinstance(lock_data, dict) and "lockfileVersion" in lock_data:
                    metadata["lockfile_version"] = lock_data["lockfileVersion"]
                if isinstance(lock_data, dict):
                    locked_packages = lock_data.get("packages")
                    if isinstance(locked_packages, dict):
                        metadata["lockfile_package_locations"] = sorted(str(path) for path in locked_packages if path)
                        for package_path, record in locked_packages.items():
                            if not package_path or not isinstance(record, dict):
                                continue
                            version = record.get("version")
                            if not isinstance(version, str):
                                continue
                            name = record.get("name")
                            if not isinstance(name, str) and "node_modules/" in package_path:
                                name = package_path.rsplit("node_modules/", 1)[1]
                            if isinstance(name, str):
                                resolved_packages.append(ResolvedPackage(
                                    name=name,
                                    version=version,
                                    source=record.get("resolved") if isinstance(record.get("resolved"), str) else None,
                                    location=package_path,
                                ))
                if package_data is not None and isinstance(lock_data, dict):
                    packages = lock_data.get("packages")
                    root_package = packages.get("") if isinstance(packages, dict) else None
                    if isinstance(root_package, dict):
                        drift: list[str] = []
                        for section in ("dependencies", "devDependencies", "optionalDependencies"):
                            manifest_values = package_data.get(section)
                            locked_values = root_package.get(section)
                            if isinstance(manifest_values, dict) and isinstance(locked_values, dict):
                                names = set(manifest_values) | set(locked_values)
                                for name in sorted(names):
                                    if manifest_values.get(name) != locked_values.get(name):
                                        drift.append(f"{section}.{name}")
                            elif bool(manifest_values) != bool(locked_values):
                                drift.append(section)
                        if drift:
                            metadata["lockfile_manifest_drift"] = drift
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                lockfile_parse_errors.append(f"{lockfile_name}: {exc}")
        if lockfile_parse_errors:
            metadata["lockfile_parse_errors"] = lockfile_parse_errors

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
            resolved_packages=sorted(resolved_packages, key=lambda item: (item.name.lower(), item.version, item.location or "")),
            metadata=metadata,
        )
