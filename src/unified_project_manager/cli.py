from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .discovery import discover
from .doctor import diagnose
from .initializer import InitializationError, execute_initialization, plan_initialization
from .operations import OperationError, execute_plan, plan_operations, render_command
from .query import duplicates as find_duplicates, resolved_duplicates as find_resolved_duplicates, why as find_why, why_resolved as find_why_resolved
from .registry import RegistryError, project_statuses, register_project, registered_paths, unregister_project
from .repair import RepairError, plan_repairs
from .sbom import cyclonedx_bom, write_cyclonedx
from .state import load_state, write_state


def _add_operation_options(parser: argparse.ArgumentParser, *, packages: bool = False, dev: bool = False, allow_all: bool = False) -> None:
    if packages:
        parser.add_argument("packages", nargs="+")
    parser.add_argument("--path", default=".", help="Project root to discover (default: current directory)")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or package name")
    parser.add_argument("--apply", action="store_true", help="Execute the native command; otherwise only preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-operation UPM doctor verification")
    if allow_all:
        parser.add_argument("--all", action="store_true", dest="all_components", help="Plan or execute every discovered component")
    if dev:
        parser.add_argument("--dev", action="store_true", help="Add as a development dependency")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm", description="Unified Project Manager")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new project using a native generator")
    init_parser.add_argument("target", nargs="?", default=".")
    init_parser.add_argument("--ecosystem", required=True, choices=("node", "python", "rust"))
    init_parser.add_argument("--manager", help="Native package manager/generator to delegate to")
    init_parser.add_argument("--lib", action="store_true", dest="library", help="Initialize a library where the ecosystem supports it")
    init_parser.add_argument("--apply", action="store_true", help="Execute the native initializer; otherwise only preview it")
    init_parser.add_argument("--json", action="store_true", dest="as_json")
    init_parser.add_argument("--no-verify", action="store_true", help="Skip post-initialization UPM doctor verification")

    projects_parser = subparsers.add_parser("projects", help="Manage the local machine-wide UPM project registry")
    project_subparsers = projects_parser.add_subparsers(dest="projects_command", required=True)
    projects_add = project_subparsers.add_parser("add", help="Register a project root")
    projects_add.add_argument("path", nargs="?", default=".")
    projects_add.add_argument("--registry", help="Override the user-level registry path")
    projects_add.add_argument("--json", action="store_true", dest="as_json")
    projects_remove = project_subparsers.add_parser("remove", help="Remove a project root from the registry")
    projects_remove.add_argument("path", nargs="?", default=".")
    projects_remove.add_argument("--registry", help="Override the user-level registry path")
    projects_remove.add_argument("--json", action="store_true", dest="as_json")
    projects_list = project_subparsers.add_parser("list", help="List registered project roots")
    projects_list.add_argument("--registry", help="Override the user-level registry path")
    projects_list.add_argument("--json", action="store_true", dest="as_json")
    projects_status = project_subparsers.add_parser("status", help="Re-discover and summarize every registered project")
    projects_status.add_argument("--registry", help="Override the user-level registry path")
    projects_status.add_argument("--deep", action="store_true", help="Include deep installed-state health checks")
    projects_status.add_argument("--json", action="store_true", dest="as_json")

    discover_parser = subparsers.add_parser("discover", help="Discover supported project components")
    discover_parser.add_argument("path", nargs="?", default=".")
    discover_parser.add_argument("--json", action="store_true", dest="as_json")

    doctor_parser = subparsers.add_parser("doctor", help="Check project structure and local tool availability")
    doctor_parser.add_argument("path", nargs="?", default=".")
    doctor_parser.add_argument("--json", action="store_true", dest="as_json")
    doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero for warnings as well as errors")
    doctor_parser.add_argument("--deep", action="store_true", help="Inspect installed environments in addition to structural project state")

    graph_parser = subparsers.add_parser("graph", help="Print normalized direct dependency information")
    graph_parser.add_argument("path", nargs="?", default=".")
    graph_parser.add_argument("--resolved", action="store_true", help="Show packages parsed from native lockfiles instead of direct declarations")
    graph_parser.add_argument("--json", action="store_true", dest="as_json")

    snapshot_parser = subparsers.add_parser("snapshot", help="Record manifest and lockfile integrity checksums")
    snapshot_parser.add_argument("path", nargs="?", default=".")
    snapshot_parser.add_argument("--json", action="store_true", dest="as_json")

    sbom_parser = subparsers.add_parser("sbom", help="Export resolved package inventory as a standard SBOM")
    sbom_parser.add_argument("path", nargs="?", default=".")
    sbom_parser.add_argument("--format", choices=("cyclonedx",), default="cyclonedx")
    sbom_parser.add_argument("--output", help="Write the SBOM to a file instead of stdout")

    why_parser = subparsers.add_parser("why", help="Find direct declarations of a dependency across components")
    why_parser.add_argument("package")
    why_parser.add_argument("path", nargs="?", default=".")
    why_parser.add_argument("--resolved", action="store_true", help="Search packages parsed from native lockfiles")
    why_parser.add_argument("--json", action="store_true", dest="as_json")

    duplicates_parser = subparsers.add_parser("duplicates", help="Find repeated direct dependency declarations")
    duplicates_parser.add_argument("path", nargs="?", default=".")
    duplicates_parser.add_argument("--resolved", action="store_true", help="Inspect repeated packages from parseable native lockfiles")
    duplicates_parser.add_argument("--json", action="store_true", dest="as_json")

    install_parser = subparsers.add_parser("install", help="Install/bootstrap a component using its native manager")
    _add_operation_options(install_parser, allow_all=True)
    sync_parser = subparsers.add_parser("sync", help="Synchronize a component from its native lockfile")
    _add_operation_options(sync_parser, allow_all=True)
    add_parser = subparsers.add_parser("add", help="Add dependencies using the component's native manager")
    _add_operation_options(add_parser, packages=True, dev=True)
    remove_parser = subparsers.add_parser("remove", help="Remove dependencies using the component's native manager")
    _add_operation_options(remove_parser, packages=True)

    repair_parser = subparsers.add_parser("repair", help="Plan safe native repairs for detected installed-state drift")
    repair_parser.add_argument("path", nargs="?", default=".")
    repair_parser.add_argument("--component", help="Limit repair planning to one component")
    repair_parser.add_argument("--apply", action="store_true", help="Execute the repair plan; otherwise only preview it")
    repair_parser.add_argument("--json", action="store_true", dest="as_json")
    repair_parser.add_argument("--no-verify", action="store_true", help="Skip post-repair deep doctor verification")

    return parser


def _relative(root: Path, path: Path) -> str:
    value = path.relative_to(root)
    return "." if str(value) == "." else value.as_posix()


def _print_discovery(graph) -> None:
    if not graph.components:
        print("No supported project components found.")
        return
    for component in graph.components:
        manager = component.manager or "unknown"
        lockfiles = ", ".join(component.lockfiles) if component.lockfiles else "none"
        print(f"{_relative(graph.root, component.path):<24} {component.ecosystem:<8} manager={manager:<8} lock={lockfiles}")


def _print_graph(graph) -> None:
    if not graph.components:
        print("No supported project components found.")
        return
    for component in graph.components:
        print(component.key(graph.root))
        if not component.dependencies:
            print("  (no direct dependencies discovered)")
            continue
        for dependency in component.dependencies:
            requirement = f" {dependency.requirement}" if dependency.requirement else ""
            print(f"  [{dependency.scope}] {dependency.name}{requirement}")


def _print_report(report) -> None:
    print(f"Project health: {report.health_score}%")
    if not report.findings:
        print("✓ No structural problems detected.")
        return
    symbols = {"info": "i", "warning": "!", "error": "x"}
    for finding in report.findings:
        location = f" [{finding.component}]" if finding.component else ""
        print(f"{symbols[finding.severity]} {finding.code}{location}: {finding.message}")
        if finding.hint:
            print(f"    {finding.hint}")


def _print_plan(plan, root: Path) -> None:
    print(f"Component: {plan.component} ({plan.manager})")
    print(f"Directory: {_relative(root, plan.cwd)}")
    print(f"Command:   {render_command(plan)}")


def _operation(args, graph) -> int:
    packages = getattr(args, "packages", ())
    dev = getattr(args, "dev", False)
    all_components = getattr(args, "all_components", False)
    try:
        plans = plan_operations(graph, args.command, selector=args.component, packages=packages, dev=dev, all_components=all_components)
    except OperationError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.as_json:
            print(json.dumps({"executed": False, "plans": [plan.to_dict(graph.root) for plan in plans]}, indent=2, sort_keys=True))
        else:
            for index, plan in enumerate(plans):
                if index:
                    print()
                _print_plan(plan, graph.root)
            print("Preview only. Re-run with --apply to execute the native command" + ("s." if len(plans) > 1 else "."))
        return 0

    results = []
    for plan in plans:
        result = execute_plan(plan, graph.root, verify=False)
        results.append(result)
        if result.returncode not in (None, 0):
            break

    verification = None
    if results and all(result.returncode == 0 for result in results) and len(results) == len(plans) and not args.no_verify:
        verification = diagnose(discover(graph.root))

    if args.as_json:
        print(json.dumps({
            "results": [result.to_dict(graph.root) for result in results],
            "verification": verification.to_dict() if verification else None,
        }, indent=2, sort_keys=True))
    else:
        for index, result in enumerate(results):
            if index:
                print()
            _print_plan(result.plan, graph.root)
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if verification:
            print("\nPost-operation verification:")
            _print_report(verification)

    failed = next((result for result in results if result.returncode not in (None, 0)), None)
    if failed:
        return failed.returncode if failed.returncode and 0 < failed.returncode < 126 else 1
    if len(results) != len(plans):
        return 1
    if verification and verification.errors:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "projects":
        try:
            if args.projects_command == "add":
                root, added = register_project(args.path, args.registry)
                data = {"path": str(root), "registered": True, "added": added}
                if args.as_json:
                    print(json.dumps(data, indent=2, sort_keys=True))
                else:
                    print(("Registered" if added else "Already registered") + f": {root}")
                return 0
            if args.projects_command == "remove":
                root, removed = unregister_project(args.path, args.registry)
                data = {"path": str(root), "registered": False, "removed": removed}
                if args.as_json:
                    print(json.dumps(data, indent=2, sort_keys=True))
                else:
                    print(("Unregistered" if removed else "Not registered") + f": {root}")
                return 0 if removed else 1
            if args.projects_command == "list":
                paths = [str(path) for path in registered_paths(args.registry)]
                if args.as_json:
                    print(json.dumps({"projects": paths}, indent=2, sort_keys=True))
                elif not paths:
                    print("No projects registered.")
                else:
                    for path in paths:
                        print(path)
                return 0
            if args.projects_command == "status":
                statuses = project_statuses(args.registry, deep=args.deep)
                if args.as_json:
                    print(json.dumps({"projects": statuses}, indent=2, sort_keys=True))
                elif not statuses:
                    print("No projects registered.")
                else:
                    for status in statuses:
                        if not status.get("exists"):
                            print(f"x {status['path']} (missing)")
                            continue
                        if status.get("error"):
                            print(f"x {status['path']} ({status['error']})")
                            continue
                        health = status["health"]
                        ecosystems = ",".join(status["ecosystems"]) or "none"
                        print(f"{health['health_score']:>3}% {status['path']} components={status['components']} ecosystems={ecosystems} errors={health['summary']['errors']} warnings={health['summary']['warnings']}")
                return 0
        except RegistryError as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2

    if args.command == "init":
        root = Path.cwd().resolve()
        try:
            plan = plan_initialization(root, args.target, args.ecosystem, args.manager, library=args.library)
        except InitializationError as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2

        if not args.apply:
            if args.as_json:
                print(json.dumps({"executed": False, "plan": plan.to_dict(root)}, indent=2, sort_keys=True))
            else:
                _print_plan(plan, root)
                print("Preview only. Re-run with --apply to execute this native initializer.")
            return 0

        result = execute_initialization(plan, root, verify=not args.no_verify)
        if args.as_json:
            print(json.dumps(result.to_dict(root), indent=2, sort_keys=True))
        else:
            _print_plan(plan, root)
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
            if result.verification:
                print("\nPost-initialization verification:")
                _print_report(result.verification)
        if result.returncode not in (None, 0):
            return result.returncode if result.returncode and 0 < result.returncode < 126 else 1
        if result.verification and result.verification.errors:
            return 1
        return 0

    path = args.path
    try:
        graph = discover(path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.command == "discover":
        if args.as_json: print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
        else: _print_discovery(graph)
        return 0
    if args.command == "graph":
        if args.as_json:
            print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
        elif not args.resolved:
            _print_graph(graph)
        else:
            if not graph.components:
                print("No supported project components found.")
            for component in graph.components:
                print(component.key(graph.root))
                if not component.resolved_packages:
                    print("  (no resolved package inventory available)")
                    continue
                for package in component.resolved_packages:
                    location = f" @ {package.location}" if package.location else ""
                    print(f"  {package.name} {package.version}{location}")
        return 0
    if args.command == "snapshot":
        target = write_state(graph)
        state = load_state(graph.root) or {}
        if args.as_json:
            print(json.dumps({"path": target.relative_to(graph.root).as_posix(), "state": state}, indent=2, sort_keys=True))
        else:
            print(f"Integrity snapshot updated: {target.relative_to(graph.root).as_posix()} ({len(state.get('files', {}))} files, {len(graph.components)} components)")
        return 0
    if args.command == "sbom":
        if args.output:
            try:
                target = write_cyclonedx(graph, args.output)
            except (OSError, ValueError) as exc:
                print(f"upm: {exc}", file=sys.stderr)
                return 2
            print(str(target))
        else:
            print(json.dumps(cyclonedx_bom(graph), indent=2, sort_keys=True))
        return 0
    if args.command == "why":
        matches = find_why_resolved(graph, args.package) if args.resolved else find_why(graph, args.package)
        if args.as_json:
            print(json.dumps({"package": args.package, "resolved": args.resolved, "matches": matches}, indent=2, sort_keys=True))
        elif not matches:
            print(("No resolved packages found for" if args.resolved else "No direct declarations found for") + f" {args.package!r}.")
        else:
            for match in matches:
                if args.resolved:
                    location = f" @ {match['location']}" if match.get("location") else ""
                    print(f"{match['component']:<24} {match['name']} {match['version']}{location}")
                else:
                    requirement = f" {match['requirement']}" if match["requirement"] else ""
                    print(f"{match['component']:<24} [{match['scope']}] {match['name']}{requirement}")
        return 0 if matches else 1
    if args.command == "duplicates":
        groups = find_resolved_duplicates(graph) if args.resolved else find_duplicates(graph)
        if args.as_json:
            print(json.dumps({"duplicates": groups}, indent=2, sort_keys=True))
        elif not groups:
            print("No repeated resolved packages found." if args.resolved else "No repeated direct dependency declarations found.")
        else:
            for group in groups:
                divergence = " version-divergence" if group["version_divergence"] else ""
                print(f"{group['ecosystem']}:{group['name']} ({group['classification']}{divergence})")
                for occurrence in group["occurrences"]:
                    if args.resolved:
                        location = f" @ {occurrence['location']}" if occurrence.get("location") else ""
                        print(f"  {occurrence['component']:<24} {occurrence['version']}{location}")
                    else:
                        requirement = occurrence["requirement"] or "*"
                        print(f"  {occurrence['component']:<24} [{occurrence['scope']}] {requirement}")
        return 0
    if args.command == "repair":
        deep_report = diagnose(graph, deep=True)
        try:
            plans = plan_repairs(graph, deep_report, selector=args.component)
        except RepairError as exc:
            if args.as_json:
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"upm: {exc}", file=sys.stderr)
            return 2

        if not plans:
            data = {"executed": False, "plans": [], "diagnosis": deep_report.to_dict()}
            if args.as_json:
                print(json.dumps(data, indent=2, sort_keys=True))
            else:
                print("No safely repairable installed-state drift detected.")
                if deep_report.errors:
                    print("The project still has non-repairable errors; review 'upm doctor --deep'.")
            return 1 if deep_report.errors else 0

        if not args.apply:
            if args.as_json:
                print(json.dumps({"executed": False, "plans": [plan.to_dict(graph.root) for plan in plans], "diagnosis": deep_report.to_dict()}, indent=2, sort_keys=True))
            else:
                for index, plan in enumerate(plans):
                    if index:
                        print()
                    _print_plan(plan, graph.root)
                print("Preview only. Re-run with --apply to execute the repair plan.")
            return 0

        results = []
        for plan in plans:
            result = execute_plan(plan, graph.root, verify=False)
            results.append(result)
            if result.returncode not in (None, 0):
                break
        verification = None
        if len(results) == len(plans) and all(result.returncode == 0 for result in results) and not args.no_verify:
            verification = diagnose(discover(graph.root), deep=True)

        if args.as_json:
            print(json.dumps({
                "results": [result.to_dict(graph.root) for result in results],
                "verification": verification.to_dict() if verification else None,
            }, indent=2, sort_keys=True))
        else:
            for index, result in enumerate(results):
                if index:
                    print()
                _print_plan(result.plan, graph.root)
                if result.stdout:
                    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
            if verification:
                print("\nPost-repair verification:")
                _print_report(verification)

        failed = next((result for result in results if result.returncode not in (None, 0)), None)
        if failed:
            return failed.returncode if failed.returncode and 0 < failed.returncode < 126 else 1
        if verification and verification.errors:
            return 1
        return 0

    if args.command == "doctor":
        report = diagnose(graph, deep=args.deep)
        if args.as_json: print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else: _print_report(report)
        return 1 if report.errors or (args.strict and report.warnings) else 0
    if args.command in {"install", "sync", "add", "remove"}:
        return _operation(args, graph)
    return 2
