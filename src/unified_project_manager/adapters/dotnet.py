from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from unified_project_manager.models import Component, Dependency, ResolvedPackage, ToolchainRequirement
from .base import Adapter

_PROJECT_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}
_SOLUTION_SUFFIXES = {".sln"}
_SOLUTION_PROJECT_RE = re.compile(r'^Project\("\{[^}]+\}"\) = "[^"]+", "([^"]+)", "\{[^}]+\}"')
_SOURCE_PROPERTY_NAMES = {
    "RestoreSources",
    "RestoreAdditionalProjectSources",
    "RestorePackagesPath",
    "NuGetPackageRoot",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _directory_files(directory: Path, suffixes: set[str]) -> list[Path]:
    try:
        return sorted(
            (entry for entry in directory.iterdir() if entry.is_file() and entry.suffix.lower() in suffixes),
            key=lambda item: item.name.lower(),
        )
    except OSError:
        return []


def dotnet_solution_files(directory: Path) -> tuple[str, ...]:
    return tuple(path.name for path in _directory_files(directory, _SOLUTION_SUFFIXES))


def _parse_project(project_file: Path) -> tuple[dict[str, object], list[Dependency]]:
    metadata: dict[str, object] = {
        "name": project_file.stem,
        "dotnet_kind": "project",
        "dotnet_target": project_file.name,
    }
    dependencies: list[Dependency] = []
    try:
        tree = ET.parse(project_file)
        root = tree.getroot()
        if isinstance(root.attrib.get("Sdk"), str):
            metadata["sdk"] = root.attrib["Sdk"]

        project_references: list[str] = []
        source_properties: list[str] = []
        explicit_imports: list[str] = []
        target_frameworks: list[str] = []
        for element in root.iter():
            name = _local_name(element.tag)
            text = (element.text or "").strip()
            if name in {"TargetFramework", "TargetFrameworks"} and text:
                target_frameworks.extend(item.strip() for item in text.split(";") if item.strip())
            elif name == "ProjectReference":
                include = element.attrib.get("Include")
                if isinstance(include, str) and include.strip():
                    project_references.append(include.strip())
            elif name == "Import":
                imported = element.attrib.get("Project")
                if isinstance(imported, str) and imported.strip():
                    explicit_imports.append(imported.strip())
            elif name == "PackageReference":
                package = element.attrib.get("Include") or element.attrib.get("Update")
                if not isinstance(package, str) or not package.strip():
                    continue
                version = element.attrib.get("Version")
                if not isinstance(version, str) or not version.strip():
                    version = None
                    for child in element:
                        if _local_name(child.tag) == "Version" and (child.text or "").strip():
                            version = (child.text or "").strip()
                            break
                dependencies.append(Dependency(package.strip(), version.strip() if isinstance(version, str) else None))
            elif name in _SOURCE_PROPERTY_NAMES and text:
                source_properties.append(name)

        if target_frameworks:
            metadata["target_frameworks"] = sorted(set(target_frameworks))
        if project_references:
            metadata["dotnet_project_references"] = sorted(set(project_references))
        if source_properties:
            metadata["dotnet_source_properties"] = sorted(set(source_properties))
        if explicit_imports:
            metadata["dotnet_explicit_imports"] = sorted(set(explicit_imports))
    except (OSError, ET.ParseError) as exc:
        metadata["parse_error"] = f"{project_file.name}: {exc}"
    return metadata, dependencies


def _parse_solution(solution_file: Path) -> dict[str, object]:
    metadata: dict[str, object] = {
        "name": solution_file.stem,
        "dotnet_kind": "solution",
        "dotnet_target": solution_file.name,
    }
    try:
        members: list[str] = []
        for raw_line in solution_file.read_text(encoding="utf-8-sig").splitlines():
            match = _SOLUTION_PROJECT_RE.match(raw_line.strip())
            if not match:
                continue
            member = match.group(1).strip()
            if Path(member).suffix.lower() in _PROJECT_SUFFIXES:
                members.append(member)
        metadata["dotnet_project_references"] = sorted(set(members))
    except (OSError, UnicodeDecodeError) as exc:
        metadata["parse_error"] = f"{solution_file.name}: {exc}"
    return metadata


def _resolved_packages(directory: Path, lockfiles: list[str]) -> list[ResolvedPackage]:
    resolved: list[ResolvedPackage] = []
    for lockfile in lockfiles:
        try:
            payload = json.loads((directory / lockfile).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        dependencies = payload.get("dependencies")
        if not isinstance(dependencies, dict):
            continue
        for framework in dependencies.values():
            if not isinstance(framework, dict):
                continue
            for name, record in framework.items():
                if not isinstance(name, str) or not isinstance(record, dict):
                    continue
                version = record.get("resolved")
                if isinstance(version, str):
                    resolved.append(ResolvedPackage(name=name, version=version, location=lockfile))
    return sorted(resolved, key=lambda item: (item.name.lower(), item.version, item.location or ""))


class DotNetAdapter(Adapter):
    ecosystem = "dotnet"

    def detect(self, directory: Path) -> bool:
        return bool(_directory_files(directory, _PROJECT_SUFFIXES | _SOLUTION_SUFFIXES))

    def inspect(self, directory: Path) -> Component:
        project_files = _directory_files(directory, _PROJECT_SUFFIXES)
        solution_files = _directory_files(directory, _SOLUTION_SUFFIXES)
        manifests = [path.name for path in project_files + solution_files]
        toolchains = [ToolchainRequirement("dotnet-sdk")]

        if len(project_files) > 1:
            return Component(
                ecosystem=self.ecosystem,
                path=directory,
                manager="nuget",
                manifests=manifests,
                toolchains=toolchains,
                metadata={
                    "dotnet_kind": "ambiguous",
                    "dotnet_targets": [path.name for path in project_files],
                    "parse_error": "multiple .NET project files share one directory",
                },
            )

        if len(project_files) == 1:
            project_file = project_files[0]
            metadata, dependencies = _parse_project(project_file)
            if solution_files:
                metadata["solution_files"] = [path.name for path in solution_files]
            lock_candidates = [directory / "packages.lock.json", directory / f"packages.{project_file.stem}.lock.json"]
            lockfiles = [path.name for path in lock_candidates if path.is_file()]
            return Component(
                ecosystem=self.ecosystem,
                path=directory,
                manager="nuget",
                manifests=manifests,
                lockfiles=lockfiles,
                toolchains=toolchains,
                dependencies=sorted(dependencies, key=lambda item: (item.scope, item.name.lower(), item.requirement or "")),
                resolved_packages=_resolved_packages(directory, lockfiles),
                metadata=metadata,
            )

        if len(solution_files) > 1:
            return Component(
                ecosystem=self.ecosystem,
                path=directory,
                manager="nuget",
                manifests=manifests,
                toolchains=toolchains,
                metadata={
                    "dotnet_kind": "ambiguous",
                    "dotnet_targets": [path.name for path in solution_files],
                    "parse_error": "multiple .NET solution files share one directory",
                },
            )

        solution_file = solution_files[0]
        return Component(
            ecosystem=self.ecosystem,
            path=directory,
            manager="nuget",
            manifests=[solution_file.name],
            toolchains=toolchains,
            metadata=_parse_solution(solution_file),
        )
