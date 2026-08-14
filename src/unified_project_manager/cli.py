from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .discovery import discover
from .doctor import diagnose
from .operations import OperationError, execute_plan, plan_operations, render_command
from .query import duplicates as find_duplicates, why as find_why
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

    discover_parser = subparsers.add_parser("discover", help="Discover supported project components")
    discover_parser.add_argument("path", nargs="?", default=".")
    discover_parser.add_argument("--json", action="store_true", dest="as_json")

    doctor_parser = subparsers.add_parser("doctor", help="Check project structure and local tool availability")
    doctor_parser.add_argument("path", nargs="?", default=".")
    doctor_parser.add_argument("--json", action="store_true", dest="as_json")
    doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero for warnings as well as errors")

    graph_parser = subparsers.add_parser("graph", help="Print normalized direct dependency information")
    graph_parser.add_argument("path", nargs="?", default=".")
    graph_parser.add_argument("--json", action="store_true", dest="as_json")

    snapshot_parser = subparsers.add_parser("snapshot", help="Record manifest and lockfile integrity checksums")
    snapshot_parser.add_argument("path", nargs="?", default=".")
    snapshot_parser.add_argument("--json", action="store_true", dest="as_json")

    why_parser = subparsers.add_parser("why", help="Find direct declarations of a dependency across components")
    why_parser.add_argument("package")
    why_parser.add_argument("path", nargs="?", default=".")
    why_parser.add_argument("--json", action="store_true", dest="as_json")

    duplicates_parser = subparsers.add_parser("duplicates", help="Find repeated direct dependency declarations")
    duplicates_parser.add_argument("path", nargs="?", default=".")
    duplicates_parser.add_argument("--json", action="store_true", dest="as_json")

    install_parser = subparsers.add_parser("install", help="Install/bootstrap a component using its native manager")
    _add_operation_options(install_parser, allow_all=True)
    sync_parser = subparsers.add_parser("sync", help="Synchronize a component from its native lockfile")
    _add_operation_options(sync_parser, allow_all=True)
    add_parser = subparsers.add_parser("add", help="Add dependencies using the component's native manager")
    _add_operation_options(add_parser, packages=True, dev=True)
    remove_parser = subparsers.add_parser("remove", help="Remove dependencies using the component's native manager")
    _add_operation_options(remove_parser, packages=True)

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
        if args.as_json: print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
        else: _print_graph(graph)
        return 0
    if args.command == "snapshot":
        target = write_state(graph)
        state = load_state(graph.root) or {}
        if args.as_json:
            print(json.dumps({"path": target.relative_to(graph.root).as_posix(), "state": state}, indent=2, sort_keys=True))
        else:
            print(f"Integrity snapshot updated: {target.relative_to(graph.root).as_posix()} ({len(state.get('files', {}))} files, {len(graph.components)} components)")
        return 0
    if args.command == "why":
        matches = find_why(graph, args.package)
        if args.as_json:
            print(json.dumps({"package": args.package, "matches": matches}, indent=2, sort_keys=True))
        elif not matches:
            print(f"No direct declarations found for {args.package!r}.")
        else:
            for match in matches:
                requirement = f" {match['requirement']}" if match['requirement'] else ""
                print(f"{match['component']:<24} [{match['scope']}] {match['name']}{requirement}")
        return 0 if matches else 1
    if args.command == "duplicates":
        groups = find_duplicates(graph)
        if args.as_json:
            print(json.dumps({"duplicates": groups}, indent=2, sort_keys=True))
        elif not groups:
            print("No repeated direct dependency declarations found.")
        else:
            for group in groups:
                divergence = " version-divergence" if group["version_divergence"] else ""
                print(f"{group['ecosystem']}:{group['name']} ({group['classification']}{divergence})")
                for occurrence in group["occurrences"]:
                    requirement = occurrence["requirement"] or "*"
                    print(f"  {occurrence['component']:<24} [{occurrence['scope']}] {requirement}")
        return 0
    if args.command == "doctor":
        report = diagnose(graph)
        if args.as_json: print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else: _print_report(report)
        return 1 if report.errors or (args.strict and report.warnings) else 0
    if args.command in {"install", "sync", "add", "remove"}:
        return _operation(args, graph)
    return 2
