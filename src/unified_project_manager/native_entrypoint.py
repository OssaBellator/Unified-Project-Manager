from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections import defaultdict
from pathlib import Path

from .discovery import discover
from .native_graph import (
    NativeGraphError,
    NativeGraphResult,
    execute_native_graph,
    plan_native_graph,
    query_native_why,
)
from .registry import RegistryError, registered_paths
from .sbom import cyclonedx_bom_with_native, write_cyclonedx_with_native


def _existing_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def _native_graph_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm graph --native", description="Query authoritative live native dependency graphs")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit native graph querying to one component")
    parser.add_argument("--preview", action="store_true", help="Show native read-only graph commands without executing them")
    parser.add_argument("--all-edges", action="store_true", help="Show requirement edges from non-selected module versions as well")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _native_why_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm why --native", description="Ask native tooling why a module is needed")
    parser.add_argument("module")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Limit the native why query to one component")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _native_fleet_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"upm projects {command} --native")
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def _native_sbom_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm sbom --native", description="Export an SBOM enriched by authoritative live native inventory")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--format", choices=("cyclonedx",), default="cyclonedx")
    parser.add_argument("--component", help="Limit live native enrichment to one component")
    parser.add_argument("--output", help="Write the SBOM to a file instead of stdout")
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    return parser


def native_graph_command(argv: list[str]) -> int:
    args = _native_graph_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        graph = discover(root)
        plans, skips = plan_native_graph(graph, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeGraphError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2) if args.as_json else f"upm: {exc}", file=sys.stdout if args.as_json else sys.stderr)
        return 2

    if args.preview:
        payload = {"executed": False, "plans": [plan.to_dict(root) for plan in plans], "skips": [skip.to_dict() for skip in skips]}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for plan in plans:
                print(f"{plan.component}: {shlex.join(plan.selected_argv)}")
                print(f"{plan.component}: {shlex.join(plan.edges_argv)}")
            for skip in skips:
                print(f"- {skip.component}: skipped ({skip.reason})")
        return 0 if plans else 1

    results = [execute_native_graph(plan) for plan in plans]
    if args.as_json:
        print(json.dumps({
            "results": [result.to_dict(root) for result in results],
            "skips": [skip.to_dict() for skip in skips],
        }, indent=2, sort_keys=True))
    else:
        for result in results:
            print(result.plan.component)
            if not result.succeeded:
                print(f"  x native graph failed: {result.stderr}")
                continue
            print("  selected build list:")
            for module in result.modules:
                if module.main:
                    continue
                rendered = f"{module.name} {module.version or ''}".rstrip()
                if module.replacement_name:
                    replacement = module.replacement_name
                    if module.replacement_version:
                        replacement += f" {module.replacement_version}"
                    rendered += f" => {replacement}"
                print(f"    {rendered}")
            print("  requirement edges:" + ("" if args.all_edges else " (selected source versions)"))
            for edge in result.edges:
                if not args.all_edges and not edge.source_selected:
                    continue
                source = edge.source_name + (f"@{edge.source_version}" if edge.source_version else "")
                target = edge.target_name + (f"@{edge.required_version}" if edge.required_version else "")
                selected = ""
                if edge.selected_version and edge.selected_version != edge.required_version:
                    selected = f" [selected {edge.selected_version}]"
                print(f"    {source} -> {target}{selected}")
        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")
    return 0 if results and all(result.succeeded for result in results) else 1


def native_why_command(argv: list[str]) -> int:
    args = _native_why_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        results, skips = query_native_why(discover(root), args.module, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeGraphError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2) if args.as_json else f"upm: {exc}", file=sys.stdout if args.as_json else sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps({"module": args.module, "results": [result.to_dict() for result in results], "skips": [skip.to_dict() for skip in skips]}, indent=2, sort_keys=True))
    else:
        for result in results:
            print(result.component)
            if not result.succeeded:
                print(f"  x native why failed: {result.stderr}")
            elif not result.needed:
                print(f"  (main module does not need {args.module})")
            else:
                for index, item in enumerate(result.path):
                    print(f"  {'->' if index else '  '} {item}")
        for skip in skips:
            print(f"- {skip.component}: skipped ({skip.reason})")
    if any(not result.succeeded for result in results):
        return 1
    return 0 if any(result.needed for result in results) else 1


def _collect_fleet_native(registry: str | None) -> tuple[list[tuple[Path, NativeGraphResult]], list[dict[str, object]], list[str]]:
    collected: list[tuple[Path, NativeGraphResult]] = []
    skips: list[dict[str, object]] = []
    missing: list[str] = []
    for root in registered_paths(registry):
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            graph = discover(root)
            plans, project_skips = plan_native_graph(graph)
        except (OSError, ValueError):
            missing.append(str(root))
            continue
        for skip in project_skips:
            skips.append(dict(skip.to_dict(), project=str(root)))
        for plan in plans:
            collected.append((root, execute_native_graph(plan)))
    return collected, skips, missing


def native_projects_inventory_command(argv: list[str]) -> int:
    args = _native_fleet_parser("inventory").parse_args(argv)
    try:
        collected, skips, missing = _collect_fleet_native(args.registry)
    except RegistryError as exc:
        print(json.dumps({"error": str(exc)}, indent=2) if args.as_json else f"upm: {exc}", file=sys.stdout if args.as_json else sys.stderr)
        return 2
    inventory = []
    failures = []
    for root, result in collected:
        if not result.succeeded:
            failures.append({"project": str(root), "component": result.plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for module in result.modules:
            if module.main:
                continue
            inventory.append(dict(module.to_dict(), project=str(root), ecosystem="go", manager="go"))
    inventory.sort(key=lambda item: (item["effective_name"], item.get("effective_version") or "", item["project"], item["component"]))
    if args.as_json:
        print(json.dumps({"inventory": inventory, "failures": failures, "skips": skips, "missing": missing}, indent=2, sort_keys=True))
    else:
        for item in inventory:
            version = item.get("version") or "(local/unversioned)"
            rendered = f"{item['effective_name']} {item.get('effective_version') or version}"
            if item["name"] != item["effective_name"]:
                rendered += f" (replaces {item['name']} {item.get('version') or ''})"
            print(f"{item['project']} [{item['component']}] {rendered}")
        for failure in failures:
            print(f"x {failure['project']} [{failure['component']}]: {failure['error']}")
    return 1 if failures else 0


def native_projects_duplicates_command(argv: list[str]) -> int:
    args = _native_fleet_parser("duplicates").parse_args(argv)
    try:
        collected, skips, missing = _collect_fleet_native(args.registry)
    except RegistryError as exc:
        print(json.dumps({"error": str(exc)}, indent=2) if args.as_json else f"upm: {exc}", file=sys.stdout if args.as_json else sys.stderr)
        return 2
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    failures = []
    for root, result in collected:
        if not result.succeeded:
            failures.append({"project": str(root), "component": result.plan.component, "error": result.stderr, "returncode": result.returncode})
            continue
        for module in result.modules:
            if module.main or not module.effective_version:
                continue
            groups[module.effective_name].append(dict(module.to_dict(), project=str(root)))
    duplicates = []
    for name, occurrences in sorted(groups.items()):
        projects = {str(item["project"]) for item in occurrences}
        if len(projects) < 2:
            continue
        versions = {str(item["effective_version"]) for item in occurrences}
        duplicates.append({"ecosystem": "go", "name": name, "projects": len(projects), "version_divergence": len(versions) > 1, "occurrences": occurrences})
    if args.as_json:
        print(json.dumps({"duplicates": duplicates, "failures": failures, "skips": skips, "missing": missing}, indent=2, sort_keys=True))
    else:
        if not duplicates:
            print("No repeated concrete native Go modules found across registered projects.")
        for group in duplicates:
            divergence = " version-divergence" if group["version_divergence"] else ""
            print(f"go:{group['name']} ({group['projects']} projects{divergence})")
            for item in group["occurrences"]:
                print(f"  {item['project']} [{item['component']}] {item['effective_version']}")
    return 1 if failures else 0


def native_sbom_command(argv: list[str]) -> int:
    args = _native_sbom_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        graph = discover(root)
        plans, _skips = plan_native_graph(graph, selector=args.component)
    except (FileNotFoundError, NotADirectoryError, NativeGraphError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2
    results = [execute_native_graph(plan) for plan in plans]
    failures = [result for result in results if not result.succeeded]
    if failures:
        for result in failures:
            print(f"upm: native inventory failed for {result.plan.component}: {result.stderr}", file=sys.stderr)
        return 1
    if args.output:
        try:
            target = write_cyclonedx_with_native(graph, results, args.output)
        except (OSError, ValueError) as exc:
            print(f"upm: {exc}", file=sys.stderr)
            return 2
        print(str(target))
    else:
        print(json.dumps(cyclonedx_bom_with_native(graph, results), indent=2, sort_keys=True))
    return 0


def dispatch_native_command(arguments: list[str]) -> int | None:
    if not arguments or "--native" not in arguments:
        return None
    if arguments[0] == "graph":
        return native_graph_command(arguments[1:])
    if arguments[0] == "why":
        return native_why_command(arguments[1:])
    if arguments[0] == "sbom":
        return native_sbom_command(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "projects" and arguments[1] == "inventory":
        return native_projects_inventory_command(arguments[2:])
    if len(arguments) >= 2 and arguments[0] == "projects" and arguments[1] == "duplicates":
        return native_projects_duplicates_command(arguments[2:])
    return None
