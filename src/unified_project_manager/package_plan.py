from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .discovery import discover
from .models import Operation, ProjectGraph
from .operations import OperationError, plan_operation, select_component

PACKAGE_PLAN_SCHEMA_VERSION = 1
PACKAGE_OPERATIONS = frozenset({"install", "sync", "add", "remove"})
SUPPORTED_PACKAGE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun", "uv", "poetry", "pdm", "pip", "cargo", "go"})

_NODE_PACKAGE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(?:@[a-z0-9*~^<>=][a-z0-9.*+~^<>=_-]*)?$", re.IGNORECASE)
_PYTHON_PACKAGE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?"
    r"(?:(?:===|==|~=|!=|<=|>=|<|>)[A-Za-z0-9*.+!_-]+(?:,(?:===|==|~=|!=|<=|>=|<|>)[A-Za-z0-9*.+!_-]+)*)?$"
)
_POETRY_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:@[A-Za-z0-9*.+~^<>=_-]+)?$")
_CARGO_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:@[A-Za-z0-9*.+~^<>=_-]+)?$")
_GO_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+/-]*(?:@[A-Za-z0-9][A-Za-z0-9._~+/-]*)?$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_SOURCE_PREFIX = re.compile(r"^(?:file|https?|git(?:\+ssh)?|ssh):", re.IGNORECASE)


def validate_executor_package_spec(manager: str, package: str, *, operation: Operation) -> str:
    """Validate the deliberately narrow package grammar exposed to automated executors.

    The human CLI may accept native-manager syntax that this boundary intentionally refuses.
    In particular, URL/VCS/local-path sources, whitespace, option-like package tokens, and
    manager-specific escape hatches are not representable in schemaVersion 1.
    """
    if operation not in PACKAGE_OPERATIONS:
        raise OperationError(f"Operation '{operation}' is not a package operation in schemaVersion {PACKAGE_PLAN_SCHEMA_VERSION}.")
    if manager not in SUPPORTED_PACKAGE_MANAGERS:
        raise OperationError(f"Package manager '{manager}' is not supported by the executor contract.")
    if not isinstance(package, str) or not package or len(package) > 512:
        raise OperationError("Executor package specs must be non-empty strings of at most 512 characters.")
    if any(character.isspace() for character in package) or any(character in package for character in "\0\r\n"):
        raise OperationError(f"Unsafe executor package spec '{package}': whitespace/control characters are not allowed.")
    if package.startswith("-"):
        raise OperationError(f"Unsafe executor package spec '{package}': option-like package tokens are not allowed.")
    if _SOURCE_PREFIX.match(package) or ":" in package:
        raise OperationError(f"Unsafe executor package spec '{package}': URL, VCS, alias, and local-source forms are not allowed.")
    if package.startswith(("/", "\\", "./", "../", "~")) or _WINDOWS_ABSOLUTE.match(package) or "\\" in package:
        raise OperationError(f"Unsafe executor package spec '{package}': local path forms are not allowed.")

    valid = False
    if manager in {"npm", "pnpm", "yarn", "bun"}:
        valid = bool(_NODE_PACKAGE.fullmatch(package))
    elif manager in {"uv", "pdm", "pip"}:
        valid = bool(_PYTHON_PACKAGE.fullmatch(package))
    elif manager == "poetry":
        valid = bool(_PYTHON_PACKAGE.fullmatch(package) or _POETRY_PACKAGE.fullmatch(package))
    elif manager == "cargo":
        valid = bool(_CARGO_PACKAGE.fullmatch(package))
    elif manager == "go":
        valid = bool(_GO_PACKAGE.fullmatch(package)) and "//" not in package and ".." not in package and not package.endswith("/")
        if valid and operation == "remove" and "@" in package:
            valid = False

    if not valid:
        raise OperationError(f"Package spec '{package}' is outside the safe schemaVersion 1 grammar for {manager}.")
    return package


def package_execution_plan(
    graph: ProjectGraph,
    operation: Operation,
    selector: str | None = None,
    packages: Sequence[str] = (),
    dev: bool = False,
) -> dict[str, Any]:
    """Return the stable, authority-free package plan consumed by constrained executors."""
    if operation not in PACKAGE_OPERATIONS:
        raise OperationError(f"Operation '{operation}' is not a package operation in schemaVersion {PACKAGE_PLAN_SCHEMA_VERSION}.")
    component = select_component(graph, selector)
    if not component.manager:
        raise OperationError(f"Cannot {operation}: package manager is unknown for this component.")
    package_tuple = tuple(
        validate_executor_package_spec(component.manager, package, operation=operation)
        for package in packages
    )
    plan = plan_operation(graph, operation, selector=selector, packages=package_tuple, dev=dev)
    relative_cwd = plan.cwd.relative_to(graph.root).as_posix() or "."
    return {
        "schemaVersion": PACKAGE_PLAN_SCHEMA_VERSION,
        "operation": operation,
        "component": plan.component,
        "ecosystem": component.ecosystem,
        "manager": plan.manager,
        "cwd": relative_cwd,
        "packages": list(package_tuple),
        "dev": bool(dev),
        "argv": list(plan.argv),
        "mutationScope": {"workspace": True, "external": False},
        "networkRequired": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upm package-plan",
        description="Emit the strict schemaVersion=1 package-operation plan for a constrained executor.",
    )
    parser.add_argument("operation", choices=tuple(sorted(PACKAGE_OPERATIONS)))
    parser.add_argument("packages", nargs="*")
    parser.add_argument("--path", default=".")
    parser.add_argument("--component")
    parser.add_argument("--dev", action="store_true")
    return parser


def dispatch_package_plan_command(argv: list[str]) -> int | None:
    if not argv or argv[0] != "package-plan":
        return None
    args = _parser().parse_args(argv[1:])
    try:
        root = Path(args.path).expanduser().resolve()
        if not root.is_dir():
            raise OperationError(f"project path is not a directory: {root}")
        plan = package_execution_plan(
            discover(root),
            args.operation,
            selector=args.component,
            packages=args.packages,
            dev=args.dev,
        )
    except (FileNotFoundError, NotADirectoryError, OperationError, ValueError) as exc:
        print(json.dumps({"schemaVersion": PACKAGE_PLAN_SCHEMA_VERSION, "error": str(exc)}, indent=2, sort_keys=True))
        return 2
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0
