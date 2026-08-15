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
from .native_graph import NativeGraphResult, plan_native_graph
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "package_count": self.package_count,
            "package_count_exact": self.package_count_exact,
            "native_go": self.native_go,
            "argv": list(self.argv_template),
            "network_may_be_used": True,
            "native_go_inventory_network": "offline" if self.native_go else "not-used",
            "temporary_sbom": True,
        }


@dataclass
class SecurityScanResult:
    plan: SecurityScanPlan
    returncode: int
    report: dict[str, Any] | None = None
    stderr: str = ""

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
        return {
            "plan": self.plan.to_dict(),
            "returncode": self.returncode,
            "scanner_succeeded": self.scanner_succeeded,
            "vulnerable": self.vulnerable,
            "summary": self.summary,
            "report": self.report,
            "stderr": self.stderr,
        }


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
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
) -> dict[str, Any]:
    if native_go:
        return cyclonedx_bom_with_native(graph, _native_go_results(graph, execute=execute_go))
    return cyclonedx_bom(graph)


def plan_security_scan(graph: ProjectGraph, *, native_go: bool = False) -> SecurityScanPlan:
    static_bom = cyclonedx_bom(graph)
    static_count = len(static_bom.get("components", [])) if isinstance(static_bom.get("components"), list) else 0
    has_go = any(component.ecosystem == "go" for component in graph.components)
    if static_count == 0 and not (native_go and has_go):
        hint = " Re-run with --native-go for authoritative selected Go modules." if has_go and not native_go else ""
        raise SecurityScanError("No concrete resolved packages are available for SBOM advisory scanning." + hint)
    return SecurityScanPlan(
        graph.root,
        static_count,
        package_count_exact=not (native_go and has_go),
        native_go=native_go,
    )


def execute_security_scan(
    graph: ProjectGraph,
    plan: SecurityScanPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
) -> SecurityScanResult:
    executable = which("osv-scanner")
    if executable is None:
        return SecurityScanResult(plan, 127, stderr="Executable 'osv-scanner' is not available on PATH.")

    bom = build_security_bom(graph, native_go=plan.native_go, execute_go=execute_go)
    package_count = len(bom.get("components", [])) if isinstance(bom.get("components"), list) else 0
    if package_count == 0:
        return SecurityScanResult(plan, 128, stderr="No concrete packages were available after native inventory enrichment.")

    with tempfile.TemporaryDirectory(prefix="upm-osv-") as temporary:
        sbom = Path(temporary) / "bom.cdx.json"
        sbom.write_text(json.dumps(bom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        argv = [executable, "scan", "source", "--format", "json", str(sbom)]
        try:
            completed = run(argv, cwd=graph.root, text=True, capture_output=True, check=False)
        except OSError as exc:
            return SecurityScanResult(plan, 127, stderr=str(exc))

    report = None
    if (completed.stdout or "").strip():
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return SecurityScanResult(plan, 127, stderr=f"Could not parse OSV-Scanner JSON output: {exc}")
        if not isinstance(parsed, dict):
            return SecurityScanResult(plan, 127, stderr="OSV-Scanner JSON output root is not an object.")
        report = parsed
    return SecurityScanResult(plan, completed.returncode, report, completed.stderr or "")
