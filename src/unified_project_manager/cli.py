from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .discovery import discover
from .doctor import diagnose
from .operations import OperationError, execute_plan, plan_operation, render_command
from .state import load_state, write_state


def _add_operation_options(parser: argparse.ArgumentParser, *, packages: bool = False, dev: bool = False) -> None:
    if packages:
        parser.add_argument("packages", nargs="+")
    parser.add_argument("--path", default=".", help="Project root to discover (default: current directory)")
    parser.add_argument("--component", help="Component key, relative path, ecosystem, or package name")
    parser.add_argument("--apply", action="store_true", help="Execute the native command; otherwise only preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-operation UPM doctor verification")
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

    install_parser = subparsers.add_parser("install", help="Install/bootstrap a component using its native manager")
    _add_operation_options(install_parser)
    sync_parser = subparsers.add_parser("sync", help="Synchronize a component from its native lockfile")
    _add_operation_options(sync_parser)
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
    try:
        plan = plan_operation(graph, args.command, selector=args.component, packages=packages, dev=dev)
    except OperationError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.as_json:
            print(json.dumps({"executed": False, "plan": plan.to_dict(graph.root)}, indent=2, sort_keys=True))
        else:
            _print_plan(plan, graph.root)
            print("Preview only. Re-run with --apply to execute this native command.")
        return 0

    result = execute_plan(plan, graph.root, verify=not args.no_verify)
    if args.as_json:
        print(json.dumps(result.to_dict(graph.root), indent=2, sort_keys=True))
    else:
        _print_plan(plan, graph.root)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.verification:
            print("\nPost-operation verification:")
            _print_report(result.verification)

    if result.returncode not in (None, 0):
        return result.returncode if 0 < result.returncode < 126 else 1
    if result.verification and result.verification.errors:
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
    if args.command == "doctor":
        report = diagnose(graph)
        if args.as_json: print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else: _print_report(report)
        return 1 if report.errors or (args.strict and report.warnings) else 0
    if args.command in {"install", "sync", "add", "remove"}:
        return _operation(args, graph)
    return 2
