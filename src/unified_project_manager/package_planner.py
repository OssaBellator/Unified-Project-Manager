from __future__ import annotations

from collections.abc import Sequence

from .models import CommandPlan, Component, Operation, ProjectGraph


class OperationError(ValueError):
    """Raised when a requested cross-ecosystem operation cannot be planned safely."""


def select_component(graph: ProjectGraph, selector: str | None) -> Component:
    if not graph.components:
        raise OperationError("No supported project components were discovered.")
    if selector is None:
        if len(graph.components) == 1:
            return graph.components[0]
        choices = ", ".join(component.key(graph.root) for component in graph.components)
        raise OperationError(f"Multiple components found; select one with --component. Choices: {choices}")

    exact = [component for component in graph.components if component.key(graph.root) == selector]
    if len(exact) == 1:
        return exact[0]

    matches = []
    for component in graph.components:
        relative = component.relative_path(graph.root)
        name = component.metadata.get("name")
        if selector in {relative, component.ecosystem} or (isinstance(name, str) and selector == name):
            matches.append(component)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(component.key(graph.root) for component in matches)
        raise OperationError(f"Component selector '{selector}' is ambiguous: {choices}")
    raise OperationError(f"Unknown component '{selector}'.")


def _yarn_sync_flag(component: Component) -> str:
    declared = component.metadata.get("package_manager_declared")
    if isinstance(declared, str) and declared.startswith("yarn@"):
        version = declared.removeprefix("yarn@").split(".", 1)[0]
        try:
            if int(version) >= 2:
                return "--immutable"
        except ValueError:
            pass
    return "--frozen-lockfile"


def _validate_component(component: Component, operation: Operation) -> None:
    if component.metadata.get("parse_error"):
        raise OperationError(f"Cannot {operation}: the component manifest is invalid.")
    if len(component.lockfiles) > 1:
        raise OperationError(
            f"Cannot {operation}: multiple native lockfiles make the authoritative package manager ambiguous "
            f"({', '.join(component.lockfiles)})."
        )
    declarations = component.metadata.get("manager_declarations")
    if isinstance(declarations, list) and len(declarations) > 1:
        raise OperationError(
            f"Cannot {operation}: multiple package managers are configured in the manifest "
            f"({', '.join(map(str, declarations))})."
        )
    declared = component.metadata.get("manager_from_manifest")
    locked = component.metadata.get("manager_from_lock")
    if declared and locked and declared != locked:
        raise OperationError(f"Cannot {operation}: manifest declares {declared} but the lockfile belongs to {locked}.")


def _require_lockfile(component: Component, operation: Operation) -> None:
    if operation == "sync" and component.manager != "go" and not component.lockfiles:
        raise OperationError(
            f"Cannot sync {component.ecosystem} component without a native lockfile; "
            "run install/lock with the native manager first."
        )


def _plan_argv(component: Component, operation: Operation, packages: tuple[str, ...], dev: bool) -> tuple[str, ...]:
    manager = component.manager
    if not manager:
        raise OperationError(f"Cannot {operation}: package manager is unknown for this component.")
    _validate_component(component, operation)

    if operation in {"add", "remove"} and not packages:
        raise OperationError(f"{operation} requires at least one package.")
    if operation in {"install", "sync"} and packages:
        raise OperationError(f"{operation} does not accept package arguments.")
    if dev and operation != "add":
        raise OperationError("--dev is only valid with add.")

    _require_lockfile(component, operation)

    if manager == "npm":
        if operation == "install":
            return ("npm", "install")
        if operation == "sync":
            return ("npm", "ci")
        if operation == "add":
            return ("npm", "install", *(("--save-dev",) if dev else ()), *packages)
        return ("npm", "uninstall", *packages)

    if manager == "pnpm":
        if operation == "install":
            return ("pnpm", "install")
        if operation == "sync":
            return ("pnpm", "install", "--frozen-lockfile")
        if operation == "add":
            return ("pnpm", "add", *(("--save-dev",) if dev else ()), *packages)
        return ("pnpm", "remove", *packages)

    if manager == "yarn":
        if operation == "install":
            return ("yarn", "install")
        if operation == "sync":
            return ("yarn", "install", _yarn_sync_flag(component))
        if operation == "add":
            return ("yarn", "add", *(("--dev",) if dev else ()), *packages)
        return ("yarn", "remove", *packages)

    if manager == "bun":
        if operation == "install":
            return ("bun", "install")
        if operation == "sync":
            return ("bun", "install", "--frozen-lockfile")
        if operation == "add":
            return ("bun", "add", *(("--dev",) if dev else ()), *packages)
        return ("bun", "remove", *packages)

    if manager == "uv":
        if operation == "install":
            return ("uv", "sync")
        if operation == "sync":
            return ("uv", "sync", "--locked")
        if operation == "add":
            return ("uv", "add", *(("--dev",) if dev else ()), *packages)
        return ("uv", "remove", *packages)

    if manager == "poetry":
        if operation == "install":
            return ("poetry", "install")
        if operation == "sync":
            return ("poetry", "sync")
        if operation == "add":
            return ("poetry", "add", *(("--group", "dev") if dev else ()), *packages)
        return ("poetry", "remove", *packages)

    if manager == "pdm":
        if operation == "install":
            return ("pdm", "install")
        if operation == "sync":
            return ("pdm", "sync")
        if operation == "add":
            return ("pdm", "add", *(("--dev",) if dev else ()), *packages)
        return ("pdm", "remove", *packages)

    if manager == "pip":
        requirement_files = [
            name for name in component.manifests if name.startswith("requirements") and name.endswith(".txt")
        ]
        if operation == "install" and requirement_files:
            args: list[str] = ["python", "-m", "pip", "install"]
            for requirement_file in requirement_files:
                args.extend(("-r", requirement_file))
            return tuple(args)
        raise OperationError(
            f"pip does not provide a safe native '{operation}' project-manifest operation; "
            "use a pyproject-aware manager or the native pip workflow."
        )

    if manager == "cargo":
        if operation == "install":
            return ("cargo", "fetch")
        if operation == "sync":
            return ("cargo", "fetch", "--locked")
        if operation == "add":
            return ("cargo", "add", *(("--dev",) if dev else ()), *packages)
        return ("cargo", "remove", *packages)

    if manager == "go":
        if dev:
            raise OperationError("Go modules do not have a native development-dependency scope for 'go get'.")
        if operation in {"install", "sync"}:
            return ("go", "mod", "download")
        if operation == "add":
            return ("go", "get", *packages)
        return ("go", "get", *(f"{package}@none" for package in packages))

    raise OperationError(f"Package manager '{manager}' is not supported for delegated operations yet.")


def plan_operation(
    graph: ProjectGraph,
    operation: Operation,
    selector: str | None = None,
    packages: Sequence[str] = (),
    dev: bool = False,
) -> CommandPlan:
    component = select_component(graph, selector)
    package_tuple = tuple(packages)
    argv = _plan_argv(component, operation, package_tuple, dev)
    assert component.manager is not None
    return CommandPlan(
        operation=operation,
        component=component.key(graph.root),
        manager=component.manager,
        argv=argv,
        cwd=component.path,
        packages=package_tuple,
    )


def plan_operations(
    graph: ProjectGraph,
    operation: Operation,
    selector: str | None = None,
    packages: Sequence[str] = (),
    dev: bool = False,
    all_components: bool = False,
) -> list[CommandPlan]:
    if not all_components:
        return [plan_operation(graph, operation, selector=selector, packages=packages, dev=dev)]
    if selector is not None:
        raise OperationError("--all cannot be combined with --component.")
    if operation not in {"install", "sync"}:
        raise OperationError("--all is only supported for install and sync.")
    if not graph.components:
        raise OperationError("No supported project components were discovered.")

    plans: list[CommandPlan] = []
    errors: list[str] = []
    for component in graph.components:
        key = component.key(graph.root)
        try:
            argv = _plan_argv(component, operation, (), False)
        except OperationError as exc:
            errors.append(f"{key}: {exc}")
            continue
        assert component.manager is not None
        plans.append(CommandPlan(operation=operation, component=key, manager=component.manager, argv=argv, cwd=component.path))
    if errors:
        joined = "; ".join(errors)
        raise OperationError(f"Cannot plan {operation} --all until every component is safe: {joined}")
    return plans
