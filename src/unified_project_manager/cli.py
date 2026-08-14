from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .discovery import discover
from .doctor import diagnose


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
        print(f"{component.key(graph.root)}")
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        graph = discover(args.path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    if args.command == "discover":
        if args.as_json:
            print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
        else:
            _print_discovery(graph)
        return 0

    if args.command == "graph":
        if args.as_json:
            print(json.dumps(graph.to_dict(), indent=2, sort_keys=True))
        else:
            _print_graph(graph)
        return 0

    if args.command == "doctor":
        report = diagnose(graph)
        if args.as_json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else:
            _print_report(report)
        if report.errors or (args.strict and report.warnings):
            return 1
        return 0

    return 2
