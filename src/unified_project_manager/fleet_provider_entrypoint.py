from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from .cargo_graph import execute_cargo_graph, plan_cargo_graphs
from .discovery import discover
from .go_offline_provider import execute_native_graph_offline
from .native_graph import plan_native_graph
from .npm_graph import execute_npm_graph, plan_npm_graphs
from .registry import RegistryError, registered_paths
from .uv_graph import execute_uv_graph, plan_uv_graphs


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"upm projects {command} --native",
        description=f"{command.title()} authoritative dependency observations across registered projects",
    )
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _normalize_name(ecosystem: str, name: str) -> str:
    if ecosystem == "python":
        return re.sub(r"[-_.]+", "-", name).lower()
    if ecosystem in {"node", "rust"}:
        return name.lower()
    return name


def _inventory_project(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    graph = discover(root)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []

    go_plans, go_skips = plan_native_graph(graph)
    npm_plans = plan_npm_graphs(graph)
    cargo_plans = plan_cargo_graphs(graph)
    uv_plans = plan_uv_graphs(graph)
    handled = {plan.component for plan in [*npm_plans, *cargo_plans, *uv_plans]}
    for skip in go_skips:
        if skip.component not in handled:
            skips.append({"project": str(root), **skip.to_dict()})

    for plan in go_plans:
        result = execute_native_graph_offline(plan)
        if not result.succeeded:
            failures.append({
                "project": str(root), "provider": "go-modules", "component": plan.component,
                "returncode": result.returncode, "error": result.stderr,
            })
            continue
        for module in result.modules:
            if module.main:
                continue
            rows.append({
                "project": str(root),
                "provider": "go-modules",
                "scope": "selected-module",
                "ecosystem": "go",
                "manager": "go",
                "component": plan.component,
                "name": module.effective_name,
                "version": module.effective_version,
                "logical_name": module.name,
                "occurrence": module.name,
                "replacement": module.to_dict().get("replacement"),
                "concrete": module.effective_version is not None,
            })

    for plan in npm_plans:
        result = execute_npm_graph(plan)
        if not result.succeeded:
            failures.append({
                "project": str(root), "provider": "npm-lock-tree", "component": plan.component,
                "returncode": result.returncode, "error": result.stderr,
            })
            continue
        for package in result.packages:
            rows.append({
                "project": str(root),
                "provider": "npm-lock-tree",
                "scope": "logical-occurrence",
                "ecosystem": "node",
                "manager": "npm",
                "component": plan.component,
                "name": package.name,
                "version": package.version,
                "occurrence": package.ref,
                "direct": package.direct,
                "depth": package.depth,
                "concrete": package.version is not None,
            })

    for plan in cargo_plans:
        result = execute_cargo_graph(plan)
        if not result.succeeded:
            failures.append({
                "project": str(root), "provider": "cargo-metadata", "component": plan.component,
                "returncode": result.returncode, "error": result.stderr,
            })
            continue
        for package in result.packages:
            if package.workspace_member:
                continue
            rows.append({
                "project": str(root),
                "provider": "cargo-metadata",
                "scope": "locked-package",
                "ecosystem": "rust",
                "manager": "cargo",
                "component": plan.component,
                "name": package.name,
                "version": package.version,
                "occurrence": package.package_id,
                "source": package.source,
                "concrete": True,
            })

    for plan in uv_plans:
        result = execute_uv_graph(plan)
        if not result.succeeded:
            failures.append({
                "project": str(root), "provider": "uv-lock", "component": plan.component,
                "returncode": None, "error": result.error,
            })
            continue
        for package in result.packages:
            if package.project_member:
                continue
            rows.append({
                "project": str(root),
                "provider": "uv-lock",
                "scope": "universal-lock-package",
                "ecosystem": "python",
                "manager": "uv",
                "component": plan.component,
                "name": package.name,
                "version": package.version,
                "occurrence": package.package_id,
                "source": package.source,
                "source_kind": package.source_kind,
                "concrete": True,
            })

    rows.sort(key=lambda item: (
        item["ecosystem"], _normalize_name(item["ecosystem"], item["name"]),
        item.get("version") or "", item["provider"], item["component"], item.get("occurrence") or "",
    ))
    return rows, failures, skips


def _collect(registry: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    inventory: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    missing: list[str] = []
    for root in registered_paths(registry):
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            project_rows, project_failures, project_skips = _inventory_project(root)
        except (OSError, ValueError) as exc:
            failures.append({
                "project": str(root), "provider": None, "component": None,
                "returncode": None, "error": str(exc),
            })
            continue
        inventory.extend(project_rows)
        failures.extend(project_failures)
        skips.extend(project_skips)
    inventory.sort(key=lambda item: (
        item["ecosystem"], _normalize_name(item["ecosystem"], item["name"]),
        item.get("version") or "", item["project"], item["component"], item.get("occurrence") or "",
    ))
    return inventory, failures, skips, missing


def inventory_command(argv: list[str]) -> int:
    args = _parser("inventory").parse_args(argv)
    try:
        inventory, failures, skips, missing = _collect(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps({
            "inventory": inventory,
            "failures": failures,
            "skips": skips,
            "missing": missing,
        }, indent=2, sort_keys=True))
    else:
        if not inventory:
            print("No authoritative native dependency inventory is available across registered projects.")
        for item in inventory:
            version = item.get("version") or "(local/unversioned)"
            print(
                f"{item['ecosystem']}:{item['name']} {version}  "
                f"{item['project']} [{item['component']}] ({item['provider']})"
            )
        for failure in failures:
            print(f"x {failure['project']} [{failure.get('component') or 'project'}]: {failure['error']}")
        if missing:
            print(f"Skipped {len(missing)} missing registered project(s).")
    return 1 if failures else 0


def _duplicate_groups(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in inventory:
        if not item.get("concrete") or not item.get("version"):
            continue
        key = (item["ecosystem"], _normalize_name(item["ecosystem"], item["name"]))
        groups[key].append(item)

    duplicates: list[dict[str, Any]] = []
    for (ecosystem, normalized), occurrences in sorted(groups.items()):
        projects = {item["project"] for item in occurrences}
        if len(projects) < 2:
            continue
        versions = {item["version"] for item in occurrences}
        names = sorted({item["name"] for item in occurrences})
        duplicates.append({
            "ecosystem": ecosystem,
            "name": names[0] if names else normalized,
            "normalized_name": normalized,
            "projects": len(projects),
            "occurrences": occurrences,
            "versions": sorted(versions),
            "version_divergence": len(versions) > 1,
            "classification": "cross-project-repeat",
            "reclaimable": False,
        })
    return duplicates


def duplicates_command(argv: list[str]) -> int:
    args = _parser("duplicates").parse_args(argv)
    try:
        inventory, failures, skips, missing = _collect(args.registry)
    except RegistryError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    duplicates = _duplicate_groups(inventory)

    if args.as_json:
        print(json.dumps({
            "duplicates": duplicates,
            "failures": failures,
            "skips": skips,
            "missing": missing,
            "reclaimable": False,
        }, indent=2, sort_keys=True))
    else:
        if not duplicates:
            print("No concrete native dependencies are repeated across registered projects.")
        for group in duplicates:
            divergence = " version-divergence" if group["version_divergence"] else ""
            print(f"{group['ecosystem']}:{group['name']} ({group['projects']} projects{divergence})")
            for item in group["occurrences"]:
                print(
                    f"  {item['version']:<16} {item['project']} "
                    f"[{item['component']}] ({item['provider']})"
                )
        print("Duplicate observations are not automatic cleanup targets.")
    return 1 if failures else 0


def dispatch_fleet_provider_command(arguments: list[str]) -> int | None:
    if len(arguments) < 2 or arguments[0] != "projects" or "--native" not in arguments:
        return None
    if arguments[1] == "inventory":
        return inventory_command(arguments[2:])
    if arguments[1] == "duplicates":
        return duplicates_command(arguments[2:])
    return None
