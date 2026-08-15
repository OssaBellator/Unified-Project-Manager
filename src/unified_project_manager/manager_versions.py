from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from .models import Finding, ProjectGraph
from .toolchains import NumericVersion, satisfies_node

SUPPORTED_NODE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun"})


def _declared_requirement(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or "@" not in value:
        return None
    manager, requirement = value.split("@", 1)
    if manager not in SUPPORTED_NODE_MANAGERS or not requirement:
        return None
    return manager, requirement


def manager_version_findings(
    graph: ProjectGraph,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Finding]:
    findings: list[Finding] = []
    versions: dict[str, tuple[NumericVersion | None, str | None]] = {}

    for component in graph.components:
        if component.ecosystem != "node":
            continue
        declared = _declared_requirement(component.metadata.get("package_manager_declared"))
        if declared is None:
            continue
        manager, requirement = declared
        if component.manager != manager or which(manager) is None:
            continue
        if manager not in versions:
            try:
                completed = run([manager, "--version"], text=True, capture_output=True, check=False)
            except OSError as exc:
                versions[manager] = (None, str(exc))
            else:
                output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
                if completed.returncode != 0:
                    versions[manager] = (None, output or f"version command exited with {completed.returncode}")
                else:
                    version = NumericVersion.parse(output)
                    versions[manager] = (version, None if version is not None else output or "no parseable version")

        installed, error = versions[manager]
        key = component.key(graph.root)
        if installed is None:
            findings.append(Finding(
                "manager.version-unreadable",
                "info",
                f"Could not verify the installed {manager} version: {error}.",
                key,
                "UPM leaves the declared manager version unverified rather than assuming a mismatch.",
            ))
            continue
        compatible = satisfies_node(installed, requirement)
        if compatible is False:
            findings.append(Finding(
                "manager.version-mismatch",
                "warning",
                f"Installed {manager} {installed} does not satisfy the project declaration {requirement!r}.",
                key,
                f"Activate {manager} {requirement} (or a compatible version) before mutating this component.",
            ))
        elif compatible is None:
            findings.append(Finding(
                "manager.requirement-unverified",
                "info",
                f"Installed {manager} is {installed}, but UPM cannot safely evaluate package-manager requirement {requirement!r}.",
                key,
            ))
    return findings
