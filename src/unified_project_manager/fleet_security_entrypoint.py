from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .audit_evidence import AuditEvidenceError, build_audit_evidence, write_audit_evidence
from .discovery import discover
from .registry import RegistryError, registered_paths
from .security import SecurityScanError, SecurityScanResult, execute_security_scan, plan_security_scan
from .security_impact import correlate_advisory_impact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm projects audit",
        description="Preview or execute advisory scans across explicitly registered projects",
    )
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument(
        "--native",
        action="store_true",
        help="Use authoritative provider-backed local/offline inventory during applied scans",
    )
    parser.add_argument(
        "--native-go",
        action="store_true",
        help="Compatibility mode: use authoritative offline selected Go modules during applied scans",
    )
    parser.add_argument("--apply", action="store_true", help="Execute OSV-Scanner; preview is the default because scanning may use the network")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _vulnerability_ids(result: SecurityScanResult) -> set[str]:
    ids: set[str] = set()
    report = result.report
    if not isinstance(report, dict):
        return ids
    values = report.get("results")
    if not isinstance(values, list):
        return ids
    for value in values:
        if not isinstance(value, dict):
            continue
        packages = value.get("packages")
        if not isinstance(packages, list):
            continue
        for package in packages:
            if not isinstance(package, dict):
                continue
            vulnerabilities = package.get("vulnerabilities")
            if not isinstance(vulnerabilities, list):
                continue
            for vulnerability in vulnerabilities:
                if isinstance(vulnerability, dict) and isinstance(vulnerability.get("id"), str):
                    ids.add(vulnerability["id"])
    return ids


def _dependency_impacts(result: SecurityScanResult) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(result.report, dict) or result.native_inventory is None:
        return [], None
    inventory = result.native_inventory
    try:
        impacts = correlate_advisory_impact(
            result.report,
            go_results=inventory.go_results,
            npm_results=inventory.npm_graph_results,
            pnpm_results=inventory.pnpm_graph_results,
            yarn_results=inventory.yarn_results,
            cargo_results=inventory.cargo_results,
            uv_results=inventory.uv_results,
        )
    except ValueError as exc:
        return [], str(exc)
    return [impact.to_dict() for impact in impacts], None


def fleet_audit_command(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        roots = registered_paths(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    missing: list[str] = []
    planning_failures: list[dict[str, str]] = []
    planned: list[tuple[Path, object, object]] = []
    for root in roots:
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            graph = discover(root)
            plan = plan_security_scan(
                graph,
                native_go=args.native_go,
                native_providers=args.native,
            )
        except (OSError, ValueError, SecurityScanError) as exc:
            planning_failures.append({"project": str(root), "error": str(exc)})
            continue
        planned.append((root, graph, plan))

    if not args.apply:
        projects = [
            {"project": str(root), "plan": plan.to_dict()}
            for root, _graph, plan in planned
        ]
        payload = {
            "executed": False,
            "network_may_be_used": True,
            "provider_inventory_network": False if args.native else None,
            "native_go_inventory_network": "offline" if args.native_go and not args.native else "not-used",
            "projects": projects,
            "missing": missing,
            "planning_failures": planning_failures,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in projects:
                mode = item["plan"]["inventory_mode"]
                print(f"{item['project']}: {item['plan']['package_count']} package observation(s) [{mode}]")
            for item in planning_failures:
                print(f"- {item['project']}: skipped ({item['error']})")
            if missing:
                print(f"Skipped {len(missing)} missing registered project(s).")
            if args.native:
                print("Native provider inventory is local/offline and is not executed during preview.")
            print("Preview only. OSV-Scanner may use the network; re-run with --apply to execute and persist valid scan evidence.")
        return 0

    project_results: list[dict[str, Any]] = []
    vulnerability_ids: set[str] = set()
    inventory_failures = 0
    scanner_failures = 0
    evidence_failures = 0
    vulnerable_projects = 0
    clean_projects = 0

    for root, graph, plan in planned:
        try:
            result = execute_security_scan(graph, plan)
        except SecurityScanError as exc:
            inventory_failures += 1
            project_results.append({
                "project": str(root),
                "result": None,
                "inventory_error": str(exc),
                "dependency_impacts": [],
                "dependency_impact_warning": None,
                "evidence": None,
                "evidence_path": None,
                "evidence_error": None,
            })
            continue

        dependency_impacts, correlation_warning = _dependency_impacts(result)
        evidence = None
        evidence_path = None
        evidence_error = None
        if result.scanner_succeeded:
            vulnerability_ids.update(_vulnerability_ids(result))
            if result.vulnerable:
                vulnerable_projects += 1
            else:
                clean_projects += 1
            if result.bom is None:
                evidence_error = (
                    "OSV-Scanner completed but UPM did not retain the exact scanned SBOM; "
                    "refusing to persist unverifiable evidence."
                )
                evidence_failures += 1
            else:
                try:
                    evidence = build_audit_evidence(
                        result.bom,
                        result,
                        inventory_mode=plan.inventory_mode,
                    )
                    evidence_path = write_audit_evidence(root, evidence)
                except (AuditEvidenceError, OSError, ValueError) as exc:
                    evidence_error = str(exc)
                    evidence_failures += 1
        else:
            scanner_failures += 1

        project_results.append({
            "project": str(root),
            "result": result.to_dict(),
            "inventory_error": None,
            "dependency_impacts": dependency_impacts,
            "dependency_impact_warning": correlation_warning,
            "evidence": evidence.to_dict() if evidence else None,
            "evidence_path": str(evidence_path) if evidence_path else None,
            "evidence_error": evidence_error,
        })

    summary = {
        "projects": len(planned),
        "clean_projects": clean_projects,
        "vulnerable_projects": vulnerable_projects,
        "inventory_failures": inventory_failures,
        "scanner_failures": scanner_failures,
        "evidence_failures": evidence_failures,
        "planning_failures": len(planning_failures),
        "missing_projects": len(missing),
        "unique_vulnerabilities": len(vulnerability_ids),
    }
    payload = {
        "executed": True,
        "summary": summary,
        "projects": project_results,
        "missing": missing,
        "planning_failures": planning_failures,
    }

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for item in project_results:
            result = item["result"]
            if result is None:
                print(f"x {item['project']}: native inventory failed ({item['inventory_error']})")
                continue
            if not result["scanner_succeeded"]:
                print(f"x {item['project']}: scanner failed ({result['stderr'] or result['returncode']})")
            elif result["vulnerable"]:
                print(f"x {item['project']}: {result['summary']['vulnerabilities']} vulnerability ID(s)")
                for impact in item["dependency_impacts"]:
                    label = f"{impact['advisory_id']} {impact['package']}"
                    if impact.get("version"):
                        label += f"@{impact['version']}"
                    print(f"    {label} [{impact['provider']}] {impact['component']}")
                    for path in impact.get("paths", []):
                        print("      dependency path: " + " -> ".join(path))
            else:
                print(f"✓ {item['project']}: clean for scanned inventory")
            if item["dependency_impact_warning"]:
                print(f"    dependency-path correlation warning: {item['dependency_impact_warning']}")
            if item["evidence_path"]:
                print(f"    evidence: {item['evidence_path']}")
            if item["evidence_error"]:
                print(f"    evidence persistence error: {item['evidence_error']}")
        for item in planning_failures:
            print(f"- {item['project']}: not scanned ({item['error']})")
        if missing:
            print(f"Skipped {len(missing)} missing registered project(s).")

    if inventory_failures or scanner_failures or evidence_failures or planning_failures:
        return 2
    return 1 if vulnerable_projects else 0


def dispatch_fleet_security_command(arguments: list[str]) -> int | None:
    if len(arguments) < 2 or arguments[0] != "projects" or arguments[1] != "audit":
        return None
    return fleet_audit_command(arguments[2:])
