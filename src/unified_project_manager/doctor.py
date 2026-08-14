from __future__ import annotations

import re
import shutil
from collections import defaultdict
from collections.abc import Callable

from .models import DoctorReport, Finding, ProjectGraph
from .state import integrity_findings

MANAGER_EXECUTABLES = {
    "npm": "npm", "pnpm": "pnpm", "yarn": "yarn", "bun": "bun",
    "uv": "uv", "pip": "python", "poetry": "poetry", "pdm": "pdm", "cargo": "cargo",
}
TOOLCHAIN_EXECUTABLES = {"node": "node", "python": "python", "rust": "rustc"}


def _normalized_dependency(ecosystem: str, name: str) -> str:
    value = name.lower()
    if ecosystem == "python":
        value = re.sub(r"[-_.]+", "-", value)
    return value


def diagnose(graph: ProjectGraph, which: Callable[[str], str | None] = shutil.which) -> DoctorReport:
    report = DoctorReport(root=graph.root)
    if not graph.components:
        report.findings.append(Finding("project.empty", "warning", "No supported project manifests were discovered."))
        report.findings.extend(integrity_findings(graph))
        return report

    checked_executables: set[tuple[str, str]] = set()
    dependency_locations: dict[tuple[str, str], list[tuple[str, str | None]]] = defaultdict(list)

    for component in graph.components:
        key = component.key(graph.root)
        parse_error = component.metadata.get("parse_error")
        if parse_error:
            report.findings.append(Finding("manifest.invalid", "error", f"Could not parse {component.manifests[0]}: {parse_error}", key, "Fix the native manifest before attempting repair."))

        requirement_errors = component.metadata.get("requirements_errors")
        if isinstance(requirement_errors, list):
            for error in requirement_errors:
                report.findings.append(Finding("manifest.read-error", "warning", str(error), key))

        lockfile_errors = component.metadata.get("lockfile_parse_errors")
        if isinstance(lockfile_errors, list):
            for error in lockfile_errors:
                report.findings.append(Finding("lockfile.invalid", "error", str(error), key, "Regenerate or restore the native lockfile with its authoritative package manager."))
        lockfile_drift = component.metadata.get("lockfile_manifest_drift")
        if isinstance(lockfile_drift, list) and lockfile_drift:
            report.findings.append(Finding("lockfile.manifest-drift", "error", f"Native lockfile root metadata disagrees with the manifest for: {', '.join(map(str, lockfile_drift))}.", key, "Run the authoritative package manager to refresh the lockfile, then review the resulting diff."))

        if component.ecosystem == "node":
            if len(component.lockfiles) > 1:
                report.findings.append(Finding("lockfile.conflict", "error", f"Multiple Node lockfiles found: {', '.join(component.lockfiles)}", key, "Keep the lockfile for the package manager this project actually uses."))
            declared = component.metadata.get("manager_from_manifest")
            locked = component.metadata.get("manager_from_lock")
            if declared and locked and declared != locked:
                report.findings.append(Finding("manager.mismatch", "error", f"package.json declares {declared}, but the lockfile belongs to {locked}.", key, "Align packageManager and the checked-in lockfile."))
            if declared and declared not in {"npm", "pnpm", "yarn", "bun"}:
                report.findings.append(Finding("manager.unsupported", "warning", f"package.json declares unsupported package manager '{declared}'.", key))
            declarations = component.metadata.get("manager_declarations")
            if isinstance(declarations, list) and len(declarations) > 1:
                report.findings.append(Finding("manager.conflict", "error", f"package.json contains conflicting package-manager declarations: {', '.join(map(str, declarations))}.", key, "Align packageManager and devEngines.packageManager."))

        if component.ecosystem == "python":
            if len(component.lockfiles) > 1:
                report.findings.append(Finding("lockfile.conflict", "error", f"Multiple Python manager lockfiles found: {', '.join(component.lockfiles)}", key, "Keep the lockfile for the Python package manager this project actually uses."))
            declarations = component.metadata.get("manager_declarations")
            if isinstance(declarations, list) and len(declarations) > 1:
                report.findings.append(Finding("manager.conflict", "error", f"pyproject.toml contains configuration for multiple package managers: {', '.join(map(str, declarations))}.", key, "Choose one authoritative project manager or remove stale tool configuration."))
            declared = component.metadata.get("manager_from_manifest")
            locked = component.metadata.get("manager_from_lock")
            if declared and locked and declared != locked:
                report.findings.append(Finding("manager.mismatch", "error", f"pyproject.toml configures {declared}, but the lockfile belongs to {locked}.", key, "Align the Python tool configuration and checked-in lockfile."))

        if component.ecosystem in {"node", "rust"} and not component.lockfiles:
            report.findings.append(Finding("lockfile.missing", "warning", f"{component.ecosystem} component has no lockfile.", key, "Generate and commit the ecosystem's native lockfile for reproducible installs."))
        if component.ecosystem == "python" and component.manager in {"uv", "poetry", "pdm"} and not component.lockfiles:
            report.findings.append(Finding("lockfile.missing", "warning", f"Python component uses {component.manager} but has no lockfile.", key))

        if component.manager:
            executable = MANAGER_EXECUTABLES.get(component.manager, component.manager)
            marker = ("manager", executable)
            if marker not in checked_executables:
                checked_executables.add(marker)
                if which(executable) is None:
                    report.findings.append(Finding("manager.unavailable", "warning", f"Package manager executable '{executable}' is not available on PATH.", key, f"Install or activate {component.manager} before mutating this project."))
        else:
            report.findings.append(Finding("manager.unknown", "warning", f"Could not infer a package manager for this {component.ecosystem} component.", key, "Add a native lockfile or package-manager declaration."))

        for toolchain in component.toolchains:
            executable = TOOLCHAIN_EXECUTABLES.get(toolchain.name, toolchain.name)
            marker = ("toolchain", executable)
            if marker in checked_executables:
                continue
            checked_executables.add(marker)
            if which(executable) is None:
                requirement = f" ({toolchain.requirement})" if toolchain.requirement else ""
                report.findings.append(Finding("toolchain.unavailable", "warning", f"Toolchain '{toolchain.name}'{requirement} is not available on PATH.", key))

        local: dict[str, list] = defaultdict(list)
        for dependency in component.dependencies:
            normalized = _normalized_dependency(component.ecosystem, dependency.name)
            local[normalized].append(dependency)
            dependency_locations[(component.ecosystem, normalized)].append((key, dependency.requirement))
        for name, declarations in local.items():
            if len(declarations) > 1:
                rendered = ", ".join(f"{d.scope}={d.requirement or '*'}" for d in declarations)
                report.findings.append(Finding("dependency.multiple-declarations", "info", f"Dependency '{name}' is declared more than once: {rendered}.", key))

    for (ecosystem, name), declarations in sorted(dependency_locations.items()):
        component_keys = {component for component, _requirement in declarations}
        requirements = {requirement for _component, requirement in declarations if requirement}
        if len(component_keys) > 1 and len(requirements) > 1:
            rendered = ", ".join(f"{component}={requirement or '*'}" for component, requirement in declarations)
            report.findings.append(Finding("dependency.version-divergence", "info", f"{ecosystem} dependency '{name}' uses different requirements across components: {rendered}."))

    report.findings.extend(integrity_findings(graph))
    return report
