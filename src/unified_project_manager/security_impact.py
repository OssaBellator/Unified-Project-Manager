from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .cargo_graph import CargoGraphResult
from .cargo_impact import analyze_cargo_impact
from .native_graph import NativeGraphResult
from .native_impact import analyze_native_impact
from .npm_graph import NpmGraphResult
from .npm_impact import analyze_npm_impact
from .pnpm_graph import PnpmGraphResult
from .pnpm_impact import analyze_pnpm_impact
from .uv_graph import UvGraphResult
from .uv_impact import analyze_uv_impact
from .yarn_graph import YarnGraphResult
from .yarn_impact import analyze_yarn_impact


@dataclass(frozen=True)
class AdvisoryDependencyImpact:
    advisory_id: str
    ecosystem: str
    package: str
    version: str | None
    provider: str
    scope: str
    component: str
    paths: tuple[tuple[str, ...], ...]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalized_python(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _osv_packages(report: dict[str, Any]) -> list[tuple[str, str, str | None, str]]:
    found: list[tuple[str, str, str | None, str]] = []
    results = report.get("results")
    if not isinstance(results, list):
        return found
    for result in results:
        if not isinstance(result, dict):
            continue
        packages = result.get("packages")
        if not isinstance(packages, list):
            continue
        for item in packages:
            if not isinstance(item, dict):
                continue
            package = item.get("package")
            if not isinstance(package, dict):
                continue
            name = package.get("name")
            ecosystem = package.get("ecosystem")
            version = package.get("version") if isinstance(package.get("version"), str) else None
            if not isinstance(name, str) or not isinstance(ecosystem, str):
                continue
            vulnerabilities = item.get("vulnerabilities")
            if not isinstance(vulnerabilities, list):
                continue
            for vulnerability in vulnerabilities:
                if isinstance(vulnerability, dict) and isinstance(vulnerability.get("id"), str):
                    found.append((ecosystem, name, version, vulnerability["id"]))
    return found


def correlate_advisory_impact(
    report: dict[str, Any],
    *,
    go_results: list[NativeGraphResult] | None = None,
    npm_results: list[NpmGraphResult] | None = None,
    pnpm_results: list[PnpmGraphResult] | None = None,
    yarn_results: list[YarnGraphResult] | None = None,
    cargo_results: list[CargoGraphResult] | None = None,
    uv_results: list[UvGraphResult] | None = None,
) -> list[AdvisoryDependencyImpact]:
    """Correlate OSV package findings with dependency-graph path evidence.

    This is dependency reachability evidence only. It does not establish that
    vulnerable code is imported, called, exploitable, or reachable at runtime.
    """
    impacts: list[AdvisoryDependencyImpact] = []
    findings = _osv_packages(report)

    for ecosystem, name, version, advisory_id in findings:
        eco = ecosystem.lower()
        if eco in {"npm", "node"}:
            for result in npm_results or []:
                for impact in analyze_npm_impact(result, name):
                    if version and impact.version != version:
                        continue
                    impacts.append(AdvisoryDependencyImpact(
                        advisory_id, ecosystem, name, version,
                        "npm-lock-tree", "logical-dependency-tree", impact.component,
                        (impact.root_path,),
                        {"ref": impact.ref, "direct": impact.direct},
                    ))
            for result in pnpm_results or []:
                for impact in analyze_pnpm_impact(result, name):
                    if version and impact.version != version:
                        continue
                    impacts.append(AdvisoryDependencyImpact(
                        advisory_id, ecosystem, name, version,
                        "pnpm-lock-tree", "logical-dependency-tree", impact.component,
                        (impact.root_path,),
                        {
                            "ref": impact.ref,
                            "alias": impact.alias,
                            "direct": impact.direct,
                            "scope": impact.scope,
                            "workspace_project": impact.workspace_project,
                            "deduped": impact.deduped,
                        },
                    ))
            for result in yarn_results or []:
                for impact in analyze_yarn_impact(result, name):
                    if version and impact.version != version:
                        continue
                    impacts.append(AdvisoryDependencyImpact(
                        advisory_id, ecosystem, name, version,
                        "yarn-berry-resolution-graph", "berry-resolution-graph", impact.component,
                        impact.root_paths,
                        {
                            "locator": impact.locator,
                            "protocol": impact.protocol,
                            "virtual": impact.virtual,
                            "direct_dependents": list(impact.direct_dependents),
                        },
                    ))
        elif eco in {"crates.io", "cargo", "rust"}:
            for result in cargo_results or []:
                for impact in analyze_cargo_impact(result, name):
                    if version and impact.version != version:
                        continue
                    impacts.append(AdvisoryDependencyImpact(
                        advisory_id, ecosystem, name, version,
                        "cargo-metadata", "locked-offline-dependency-graph", impact.component,
                        impact.workspace_paths,
                        {"package_id": impact.package_id},
                    ))
        elif eco in {"go", "golang"}:
            for result in go_results or []:
                for impact in analyze_native_impact(result, name):
                    if version and impact.selected_version and impact.selected_version != version:
                        continue
                    impacts.append(AdvisoryDependencyImpact(
                        advisory_id, ecosystem, name, version,
                        "go-modules", "module-requirement", impact.component,
                        impact.root_paths,
                        {"module": impact.module, "effective_name": impact.effective_name},
                    ))
        elif eco in {"pypi", "python"}:
            target = _normalized_python(name)
            for result in uv_results or []:
                matches = [package for package in result.packages if _normalized_python(package.name) == target]
                if version:
                    matches = [package for package in matches if package.version == version]
                for package in matches:
                    for impact in analyze_uv_impact(result, package.name):
                        if impact.package_id != package.package_id:
                            continue
                        impacts.append(AdvisoryDependencyImpact(
                            advisory_id, ecosystem, name, version,
                            "uv-lock", "universal-lock-dependency-graph", impact.component,
                            impact.project_paths,
                            {"package_id": impact.package_id, "ambiguous_references": impact.ambiguous_references},
                        ))

    return sorted(impacts, key=lambda item: (
        item.advisory_id, item.ecosystem.lower(), item.package.lower(), item.version or "",
        item.provider, item.component, item.paths,
    ))
