from __future__ import annotations

import json
from pathlib import Path

from .models import Component, Finding, ProjectGraph


def _node_package_directories(node_modules: Path):
    """Yield physical package directories below nested node_modules trees without following links."""
    if not node_modules.is_dir():
        return
    stack = [node_modules]
    seen: set[Path] = set()
    while stack:
        current = stack.pop()
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.name.startswith("@") and entry.is_dir() and not entry.is_symlink():
                try:
                    scoped = sorted(entry.iterdir(), key=lambda item: item.name)
                except OSError:
                    continue
                for package in scoped:
                    if package.is_dir():
                        yield package
                        nested = package / "node_modules"
                        if nested.is_dir() and not nested.is_symlink():
                            stack.append(nested)
                continue
            if entry.is_dir():
                yield entry
                nested = entry / "node_modules"
                if nested.is_dir() and not nested.is_symlink():
                    stack.append(nested)


def _node_findings(component: Component, root: Path) -> list[Finding]:
    node_modules = component.path / "node_modules"
    if not node_modules.is_dir():
        return []

    component_key = component.key(root)
    expected_locations_value = component.metadata.get("lockfile_package_locations")
    if not isinstance(expected_locations_value, list):
        return []
    expected_locations = {str(value) for value in expected_locations_value if isinstance(value, str)}
    expected_versions = {
        package.location: package.version
        for package in component.resolved_packages
        if package.location and package.location.startswith("node_modules/")
    }

    findings: list[Finding] = []
    actual_locations: set[str] = set()
    for package_dir in _node_package_directories(node_modules):
        try:
            location = package_dir.relative_to(component.path).as_posix()
        except ValueError:
            continue
        actual_locations.add(location)
        metadata_file = package_dir / "package.json"
        expected_version = expected_versions.get(location)
        if expected_version is None:
            continue
        if not metadata_file.is_file():
            findings.append(Finding(
                "installed.metadata-missing",
                "error",
                f"Installed package metadata is missing at {location}/package.json.",
                component_key,
                "Reinstall or sync the component with its native package manager.",
            ))
            continue
        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(Finding(
                "installed.metadata-invalid",
                "error",
                f"Could not read installed package metadata at {location}/package.json: {exc}",
                component_key,
                "Reinstall or sync the component with its native package manager.",
            ))
            continue
        actual_version = data.get("version") if isinstance(data, dict) else None
        if actual_version != expected_version:
            findings.append(Finding(
                "installed.version-mismatch",
                "error",
                f"Installed package at {location} is version {actual_version!r}; lockfile expects {expected_version!r}.",
                component_key,
                "Reinstall or sync the component from its native lockfile.",
            ))

    for location in sorted(expected_locations - actual_locations):
        if not location.startswith("node_modules/"):
            continue
        findings.append(Finding(
            "installed.package-missing",
            "warning",
            f"Lockfile package is not installed at {location}.",
            component_key,
            "Run the component's native install/sync operation if this environment should be complete.",
        ))

    for location in sorted(actual_locations - expected_locations):
        findings.append(Finding(
            "installed.package-untracked",
            "warning",
            f"Installed package is not represented in the native lockfile: {location}.",
            component_key,
            "Remove the extraneous package or refresh the native lockfile if it is intentional.",
        ))

    return findings


def installed_findings(graph: ProjectGraph) -> list[Finding]:
    findings: list[Finding] = []
    for component in graph.components:
        if component.ecosystem == "node":
            findings.extend(_node_findings(component, graph.root))
    return findings
