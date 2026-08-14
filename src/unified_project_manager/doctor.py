from __future__ import annotations

import shutil
from collections.abc import Callable

from .models import DoctorReport, Finding, ProjectGraph

MANAGER_EXECUTABLES = {
    "npm": "npm",
    "pnpm": "pnpm",
    "yarn": "yarn",
    "bun": "bun",
    "uv": "uv",
    "pip": "python",
    "poetry": "poetry",
    "pdm": "pdm",
    "cargo": "cargo",
}

TOOLCHAIN_EXECUTABLES = {
    "node": "node",
    "python": "python",
    "rust": "rustc",
}


def diagnose(graph: ProjectGraph, which: Callable[[str], str | None] = shutil.which) -> DoctorReport:
    report = DoctorReport(root=graph.root)

    if not graph.components:
        report.findings.append(Finding("project.empty", "warning", "No supported project manifests were discovered."))
        return report

    checked_executables: set[tuple[str, str]] = set()

    for component in graph.components:
        key = component.key(graph.root)
        parse_error = component.metadata.get("parse_error")
        if parse_error:
            report.findings.append(Finding("manifest.invalid", "error", f"Could not parse {component.manifests[0]}: {parse_error}", key, "Fix the native manifest before attempting repair."))

        if component.ecosystem == "node":
            if len(component.lockfiles) > 1:
                report.findings.append(Finding("lockfile.conflict", "error", f"Multiple Node lockfiles found: {', '.join(component.lockfiles)}", key, "Keep the lockfile for the package manager this project actually uses."))
            declared = component.metadata.get("manager_from_manifest")
            locked = component.metadata.get("manager_from_lock")
            if declared and locked and declared != locked:
                report.findings.append(Finding("manager.mismatch", "error", f"package.json declares {declared}, but the lockfile belongs to {locked}.", key, "Align packageManager and the checked-in lockfile."))

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

    return report
