from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .discovery import discover
from .initializer import InitializationError, execute_initialization, plan_initialization
from .registry import RegistryError, registered_paths
from .storage import project_storage, storage_summary
from .tasks import TaskError, execute_task, list_native_tasks, load_tasks, plan_native_task, plan_task


def _storage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm storage", description="Measure project-local package/environment/build storage")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _tasks_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm tasks", description="List UPM and supported native project tasks")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm run", description="Plan or execute a UPM/native project task")
    parser.add_argument("task")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--component", help="Select a component when a native task is ambiguous")
    parser.add_argument("--apply", action="store_true", help="Execute the task plan; otherwise preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _projects_storage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm projects storage", description="Measure known artifact storage across registered projects")
    parser.add_argument("--registry", help="Override the user-level project registry")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _go_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="upm init", description="Initialize a Go module using go mod init")
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--ecosystem", required=True, choices=("go",))
    parser.add_argument("--module", required=True, help="Go module path, for example example.com/project")
    parser.add_argument("--apply", action="store_true", help="Execute go mod init; otherwise only preview it")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-initialization UPM doctor verification")
    return parser


def _existing_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def _storage(argv: list[str]) -> int:
    args = _storage_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        entries = project_storage(discover(root))
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2
    summary = storage_summary(entries)
    if args.as_json:
        print(json.dumps({"summary": summary, "entries": entries}, indent=2, sort_keys=True))
    elif not entries:
        print("No known local package/environment/build artifact directories found.")
    else:
        for entry in entries:
            mib = entry["bytes"] / (1024 * 1024)
            print(f"{mib:9.2f} MiB  {entry['category']:<11} {entry['path']} [{entry['component']}]")
        print(f"Total: {summary['bytes'] / (1024 * 1024):.2f} MiB")
    return 0


def _tasks(argv: list[str]) -> int:
    args = _tasks_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        configured = load_tasks(root)
        native = list_native_tasks(discover(root))
    except (FileNotFoundError, NotADirectoryError, TaskError, ValueError) as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2

    configured_rows = [dict(configured[name].to_dict(root), source="upm") for name in sorted(configured)]
    native_rows = [dict(item, source="native") for item in native]
    if args.as_json:
        print(json.dumps({"tasks": configured_rows + native_rows}, indent=2, sort_keys=True))
    elif not configured_rows and not native_rows:
        print("No UPM or supported native tasks discovered.")
    else:
        for row in configured_rows:
            description = f" — {row['description']}" if row.get("description") else ""
            print(f"{row['name']:<20} upm{description}")
        for row in native_rows:
            print(f"{row['name']:<20} native [{row['component']}] {shlex.join(row['argv'])}")
    return 0


def _run(argv: list[str]) -> int:
    args = _run_parser().parse_args(argv)
    try:
        root = _existing_root(args.path)
        configured = load_tasks(root)
        if args.task in configured:
            plans = plan_task(root, args.task)
        else:
            plans = [plan_native_task(discover(root), args.task, selector=args.component)]
    except (FileNotFoundError, NotADirectoryError, TaskError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2

    if not args.apply:
        if args.as_json:
            print(json.dumps({"executed": False, "tasks": [task.to_dict(root) for task in plans]}, indent=2, sort_keys=True))
        else:
            for task in plans:
                cwd = task.cwd.relative_to(root).as_posix() or "."
                print(f"{task.name}: ({cwd}) {shlex.join(task.argv)}")
            print("Preview only. Re-run with --apply to execute the task plan.")
        return 0

    results = []
    for task in plans:
        result = execute_task(task)
        results.append(result)
        if not result.succeeded:
            break
    if args.as_json:
        print(json.dumps({"results": [result.to_dict(root) for result in results]}, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"{result.task.name}: {shlex.join(result.task.argv)}")
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return 0 if len(results) == len(plans) and all(result.succeeded for result in results) else 1


def _projects_storage(argv: list[str]) -> int:
    args = _projects_storage_parser().parse_args(argv)
    entries = []
    missing = []
    try:
        roots = registered_paths(args.registry)
    except RegistryError as exc:
        print(f"upm: {exc}", file=sys.stderr)
        return 2
    for root in roots:
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            for entry in project_storage(discover(root)):
                entries.append(dict(entry, project=str(root)))
        except (OSError, ValueError):
            missing.append(str(root))
    summary = storage_summary(entries)
    if args.as_json:
        print(json.dumps({"summary": summary, "entries": entries, "missing": missing}, indent=2, sort_keys=True))
    elif not entries:
        print("No known artifact storage found across registered projects.")
    else:
        for entry in entries:
            mib = entry["bytes"] / (1024 * 1024)
            print(f"{mib:9.2f} MiB  {entry['category']:<11} {entry['project']}::{entry['path']}")
        print(f"Total: {summary['bytes'] / (1024 * 1024):.2f} MiB")
        if missing:
            print(f"Skipped {len(missing)} missing/unreadable registered project(s).")
    return 0


def _go_init(argv: list[str]) -> int:
    args = _go_init_parser().parse_args(argv)
    root = Path.cwd().resolve()
    try:
        plan = plan_initialization(root, args.target, "go", "go", module=args.module)
    except InitializationError as exc:
        if args.as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"upm: {exc}", file=sys.stderr)
        return 2
    if not args.apply:
        payload = {"executed": False, "plan": plan.to_dict(root)}
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Component: {plan.component} ({plan.manager})")
            print(f"Command:   {shlex.join(plan.argv)}")
            print("Preview only. Re-run with --apply to execute this native initializer.")
        return 0
    result = execute_initialization(plan, root, verify=not args.no_verify)
    if args.as_json:
        print(json.dumps(result.to_dict(root), indent=2, sort_keys=True))
    else:
        print(f"Command: {shlex.join(plan.argv)}")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode not in (None, 0):
        return result.returncode if result.returncode and 0 < result.returncode < 126 else 1
    if result.verification and result.verification.errors:
        return 1
    return 0


def _is_go_init(arguments: list[str]) -> bool:
    if not arguments or arguments[0] != "init":
        return False
    try:
        index = arguments.index("--ecosystem")
    except ValueError:
        return False
    return index + 1 < len(arguments) and arguments[index + 1] == "go"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "storage":
        return _storage(arguments[1:])
    if arguments and arguments[0] == "tasks":
        return _tasks(arguments[1:])
    if arguments and arguments[0] == "run":
        return _run(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "projects" and arguments[1] == "storage":
        return _projects_storage(arguments[2:])
    if _is_go_init(arguments):
        return _go_init(arguments[1:])

    from .cli import main as legacy_main
    return legacy_main(arguments)
