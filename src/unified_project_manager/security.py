from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .go_offline_provider import execute_native_graph_offline
from .models import ProjectGraph
from .native_cyclonedx import NativeCycloneDxError, NativeCycloneDxInventory, build_native_cyclonedx
from .native_graph import NativeGraphResult, plan_native_graph
from .provider_registry import provider_summary
from .sbom import cyclonedx_bom, cyclonedx_bom_with_native


class SecurityScanError(ValueError):
    """Raised when advisory scanning cannot be planned or interpreted safely."""


@dataclass(frozen=True)
class SecurityScanPlan:
    root: Path
    package_count: int
    package_count_exact: bool
    native_go: bool
    argv_template: tuple[str, ...] = (
        "osv-scanner", "scan", "source", "--format", "json", "<temporary-bom.cdx.json>"
    )
    native_providers: bool = False

    @property
    def inventory_mode(self) -> str:
        if self.native_providers:
            return "native-providers"
        if self.native_go:
            return "native-go"
        return "static-resolved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "package_count": self.package_count,
            "package_count_exact": self.package_count_exact,
            "native_go": self.native_go,
            "native_providers": self.native_providers,
            "inventory_mode": self.inventory_mode,
            "argv": list(self.argv_template),
            "network_may_be_used": True,
            "provider_inventory_network": False if self.native_providers else None,
            "temporary_sbom": True,
        }


@dataclass
class SecurityScanResult:
    plan: SecurityScanPlan
    returncode: int
    report: dict[str, Any] | None = None
    stderr: str = ""
    bom: dict[str, Any] | None = None
    native_inventory: NativeCycloneDxInventory | None = None

    @property
    def scanner_succeeded(self) -> bool:
        return self.returncode in {0, 1}

    @property
    def vulnerable(self) -> bool:
        return self.returncode == 1 and self.summary["vulnerabilities"] > 0

    @property
    def summary(self) -> dict[str, int]:
        if not isinstance(self.report, dict):
            return {"affected_packages": 0, "vulnerabilities": 0}
        affected_packages = 0
        vulnerability_ids: set[str] = set()
        results = self.report.get("results")
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                packages = result.get("packages")
                if not isinstance(packages, list):
                    continue
                for package in packages:
                    if not isinstance(package, dict):
                        continue
                    vulnerabilities = package.get("vulnerabilities")
                    if not isinstance(vulnerabilities, list) or not vulnerabilities:
                        continue
                    affected_packages += 1
                    for vulnerability in vulnerabilities:
                        if isinstance(vulnerability, dict) and isinstance(vulnerability.get("id"), str):
                            vulnerability_ids.add(vulnerability["id"])
        return {"affected_packages": affected_packages, "vulnerabilities": len(vulnerability_ids)}

    def to_dict(self) -> dict[str, Any]:
        # The exact BOM/provider objects are retained for evidence binding and
        # dependency-path correlation but intentionally not duplicated wholesale
        # into normal CLI output.
        return {
            "plan": self.plan.to_dict(),
            "returncode": self.returncode,
            "scanner_succeeded": self.scanner_succeeded,
            "vulnerable": self.vulnerable,
            "summary": self.summary,
            "report": self.report,
            "stderr": self.stderr,
            "native_provider_counts": (
                self.native_inventory.provider_counts() if self.native_inventory is not None else None
            ),
        }


def _dependency_component_count(bom: dict[str, Any]) -> int:
    """Count dependency library components, excluding project topology anchors."""
    components = bom.get("components")
    if not isinstance(components, list):
        return 0
    return sum(
        1
        for component in components
        if isinstance(component, dict) and component.get("type") == "library"
    )


def _native_go_results(
    graph: ProjectGraph,
    *,
    execute: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
) -> list[NativeGraphResult]:
    plans, _skips = plan_native_graph(graph)
    results = [execute(plan) for plan in plans]
    failures = [result for result in results if not result.succeeded]
    if failures:
        rendered = "; ".join(f"{result.plan.component}: {result.stderr}" for result in failures)
        raise SecurityScanError(f"Could not build authoritative offline Go inventory for advisory scan: {rendered}")
    return results


def build_security_bom(
    graph: ProjectGraph,
    *,
    native_go: bool = False,
    native_providers: bool = False,
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
    build_native: Callable[..., NativeCycloneDxInventory] = build_native_cyclonedx,
) -> dict[str, Any]:
    if native_providers:
        try:
            return build_native(graph, execute_go=execute_go).bom
        except NativeCycloneDxError as exc:
            raise SecurityScanError(str(exc)) from exc
    if native_go:
        return cyclonedx_bom_with_native(graph, _native_go_results(graph, execute=execute_go))
    return cyclonedx_bom(graph)


def plan_security_scan(
    graph: ProjectGraph,
    *,
    native_go: bool = False,
    native_providers: bool = False,
) -> SecurityScanPlan:
    static_bom = cyclonedx_bom(graph)
    static_count = _dependency_component_count(static_bom)
    has_go = any(component.ecosystem == "go" for component in graph.components)
    provider_coverage = provider_summary(graph)
    has_native_provider = provider_coverage["supported_components"] > 0
    can_enrich = (native_go and has_go) or (native_providers and has_native_provider)
    if static_count == 0 and not can_enrich:
        hints = []
        if has_native_provider and not native_providers:
            hints.append("Re-run with --native for authoritative provider-backed inventory.")
        elif has_go and not native_go:
            hints.append("Re-run with --native-go for authoritative selected Go modules.")
        hint = " " + " ".join(hints) if hints else ""
        raise SecurityScanError("No concrete resolved packages are available for SBOM advisory scanning." + hint)
    return SecurityScanPlan(
        graph.root,
        static_count,
        package_count_exact=not can_enrich,
        native_go=native_go,
        native_providers=native_providers,
    )


def execute_security_scan(
    graph: ProjectGraph,
    plan: SecurityScanPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
    build_native: Callable[..., NativeCycloneDxInventory] = build_native_cyclonedx,
) -> SecurityScanResult:
    executable = which("osv-scanner")
    if executable is None:
        return SecurityScanResult(plan, 127, stderr="Executable 'osv-scanner' is not available on PATH.")

    native_inventory: NativeCycloneDxInventory | None = None
    try:
        if plan.native_providers:
            native_inventory = build_native(
                graph,
                execute_go=execute_go,
                include_path_graphs=True,
            )
            bom = native_inventory.bom
        else:
            bom = build_security_bom(
                graph,
                native_go=plan.native_go,
                native_providers=False,
                execute_go=execute_go,
                build_native=build_native,
            )
    except NativeCycloneDxError as exc:
        raise SecurityScanError(str(exc)) from exc

    package_count = _dependency_component_count(bom)
    if package_count == 0:
        return SecurityScanResult(
            plan,
            128,
            stderr="No concrete packages were available after inventory enrichment.",
            bom=bom,
            native_inventory=native_inventory,
        )

    with tempfile.TemporaryDirectory(prefix="upm-osv-") as temporary:
        sbom = Path(temporary) / "bom.cdx.json"
        sbom.write_text(json.dumps(bom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        argv = [executable, "scan", "source", "--format", "json", str(sbom)]
        try:
            completed = run(argv, cwd=graph.root, text=True, capture_output=True, check=False)
        except OSError as exc:
            return SecurityScanResult(
                plan, 127, stderr=str(exc), bom=bom, native_inventory=native_inventory
            )

    report = None
    if (completed.stdout or "").strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return SecurityScanResult(
                plan,
                127,
                stderr=f"Could not parse OSV-Scanner JSON output: {exc}",
                bom=bom,
                native_inventory=native_inventory,
            )
        if not isinstance(parsed, dict):
            return SecurityScanResult(
                plan,
                127,
                stderr="OSV-Scanner JSON output root is not an object.",
                bom=bom,
                native_inventory=native_inventory,
            )
        report = parsed
    return SecurityScanResult(
        plan,
        completed.returncode,
        report,
        completed.stderr or "",
        bom,
        native_inventory,
    )
