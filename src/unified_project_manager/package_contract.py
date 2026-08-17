from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__ as PROVIDER_VERSION
from .discovery import discover
from .models import Component, ProjectGraph
from .package_planner import OperationError, plan_operation, select_component

PROVIDER_NAME = "unified-project-manager.package-operation-planner"
CONTRACT_NAME = "upm.package-operation-plan"
CONTRACT_VERSION = "1.0.0"
REQUEST_SCHEMA_VERSION = 1
ENVELOPE_SCHEMA_VERSION = 1
EXECUTION_SCHEMA_VERSION = 1
SUPPORTED_OPERATIONS = ("install", "sync", "add", "remove")
SUPPORTED_MANAGER_ECOSYSTEMS = {
    "npm": "node",
    "pnpm": "node",
    "yarn": "node",
    "bun": "node",
    "uv": "python",
    "poetry": "python",
    "pdm": "python",
    "pip": "python",
    "cargo": "rust",
    "go": "go",
}
MAX_PACKAGES = 32
MAX_PACKAGE_LENGTH = 512
MAX_SELECTOR_LENGTH = 512
MAX_ERROR_MESSAGE = 512


class PackageContractError(ValueError):
    """Stable public error for package-operation contract consumers."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        self.code = code
        self.message = _bounded_message(message)
        self.details = dict(sorted((details or {}).items()))
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _bounded_message(message: str) -> str:
    compact = " ".join(str(message).split())
    if len(compact) <= MAX_ERROR_MESSAGE:
        return compact
    return compact[: MAX_ERROR_MESSAGE - 3] + "..."


def contract_metadata() -> dict[str, Any]:
    """Return version/compatibility metadata independent of any execution payload."""

    return {
        "schemaVersion": ENVELOPE_SCHEMA_VERSION,
        "provider": {"name": PROVIDER_NAME, "version": PROVIDER_VERSION},
        "contract": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
        "compatibility": {
            "requestSchemaVersions": [REQUEST_SCHEMA_VERSION],
            "executionSchemaVersions": [EXECUTION_SCHEMA_VERSION],
            "executionConstraintKinds": ["environment"],
            "planningEffects": {
                "managerExecution": False,
                "toolInstallation": False,
                "projectWrites": False,
                "networkAccess": False,
            },
        },
    }


@dataclass(frozen=True)
class PackageOperationPlan:
    operation: str
    component: str
    ecosystem: str
    manager: str
    cwd: str
    packages: tuple[str, ...]
    dev: bool
    argv: tuple[str, ...]

    def execution_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": EXECUTION_SCHEMA_VERSION,
            "operation": self.operation,
            "component": self.component,
            "ecosystem": self.ecosystem,
            "manager": self.manager,
            "cwd": self.cwd,
            "packages": list(self.packages),
            "dev": self.dev,
            "argv": list(self.argv),
            "mutationScope": {"workspace": True, "external": False},
            "networkRequired": True,
        }

    def execution_constraints_dict(self) -> dict[str, Any]:
        environment = {"GOWORK": "off"} if self.manager == "go" else {}
        return {"environment": environment}

    def to_dict(self) -> dict[str, Any]:
        return {
            **contract_metadata(),
            "ok": True,
            "executionConstraints": self.execution_constraints_dict(),
            "execution": self.execution_dict(),
        }


def _validate_operation(operation: object) -> str:
    if not isinstance(operation, str) or operation not in SUPPORTED_OPERATIONS:
        raise PackageContractError(
            "invalid_operation",
            "operation must be one of: install, sync, add, remove",
        )
    return operation


def _validate_selector(selector: object) -> str | None:
    if selector is None:
        return None
    if not isinstance(selector, str) or not selector or len(selector) > MAX_SELECTOR_LENGTH or "\x00" in selector:
        raise PackageContractError("invalid_component", "component must be a non-empty bounded string when provided")
    return selector


def _validate_packages(packages: object) -> tuple[str, ...]:
    if isinstance(packages, (str, bytes)) or not isinstance(packages, Sequence):
        raise PackageContractError("invalid_packages", "packages must be an array of package specifier strings")
    if len(packages) > MAX_PACKAGES:
        raise PackageContractError("invalid_packages", f"packages may contain at most {MAX_PACKAGES} entries")
    normalized: list[str] = []
    for package in packages:
        if not isinstance(package, str) or not package or len(package) > MAX_PACKAGE_LENGTH:
            raise PackageContractError("invalid_package", "each package must be a non-empty bounded string")
        if package.startswith("-"):
            raise PackageContractError("invalid_package", "package specifiers may not begin with '-' because manager options are not package names")
        if any(character in package for character in ("\x00", "\r", "\n")):
            raise PackageContractError("invalid_package", "package specifiers may not contain control separators")
        normalized.append(package)
    return tuple(normalized)


def _validate_portable_package_specs(ecosystem: str, packages: tuple[str, ...]) -> None:
    for package in packages:
        path_parts = package.replace("\\", "/").split("/")
        source_like = (
            package.startswith((".", "/", "\\", "~"))
            or "\\" in package
            or ":" in package
            or "#" in package
            or any(character.isspace() for character in package)
            or ".." in path_parts
            or "../" in package
            or "..\\" in package
            or " @ " in package
        )
        node_unscoped_slash = ecosystem == "node" and "/" in package and not package.startswith("@")
        if source_like or node_unscoped_slash:
            raise PackageContractError(
                "invalid_package",
                "package specifiers must be portable registry/module identifiers, not manager options, local paths, URLs, VCS references, or aliases",
            )


def _validate_pip_requirements(project_root: Path, component_path: Path, manifests: Sequence[str]) -> None:
    for manifest in manifests:
        if not (manifest.startswith("requirements") and manifest.endswith(".txt")):
            continue
        requirement_path = (component_path / manifest).resolve()
        try:
            requirement_path.relative_to(project_root)
        except ValueError as exc:
            raise PackageContractError("external_read_scope", "pip requirement file escapes the selected project root") from exc
        try:
            lines = requirement_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise PackageContractError("discovery_failed", "pip requirement file could not be read safely") from exc
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lowered = line.lower()
            local_path = (
                line.startswith(("-", ".", "/", "\\", "~"))
                or (len(line) >= 3 and line[0].isalpha() and line[1] == ":" and line[2] in {"/", "\\"})
            )
            source_form = (
                local_path
                or line.endswith("\\")
                or " @ " in line
                or "://" in lowered
                or "git+" in lowered
                or "file:" in lowered
                or " --" in line
            )
            if source_form:
                raise PackageContractError(
                    "operation_not_safe",
                    "pip requirements use an option, include, local path, URL, VCS reference, direct source, or continuation outside the portable v1 scope",
                )


def _validate_preplan_contract_semantics(
    selected: Component,
    operation: str,
    packages: tuple[str, ...],
) -> None:
    manager = selected.manager
    metadata = selected.metadata
    if manager == "yarn" and operation == "sync":
        declared = metadata.get("package_manager_declared") if isinstance(metadata, dict) else None
        major_text = None
        if isinstance(declared, str) and declared.startswith("yarn@"):
            major_text = declared.removeprefix("yarn@").split(".", 1)[0]
        try:
            if major_text is None:
                raise ValueError
            int(major_text)
        except ValueError as exc:
            raise PackageContractError(
                "operation_not_safe",
                "yarn sync requires a declared yarn major version so frozen/immutable semantics are unambiguous",
            ) from exc
    if manager == "go":
        if operation == "remove" and any("@" in package for package in packages):
            raise PackageContractError("invalid_package", "go remove targets must be unversioned module paths")
        if operation == "add" and any(package.endswith("@none") for package in packages):
            raise PackageContractError("invalid_package", "go add targets may not use the removal sentinel @none")
    if manager == "pip" and operation != "install":
        raise PackageContractError(
            "operation_not_safe",
            "pip v1 supports only requirements-file install planning; sync/add/remove require a project-aware manager",
        )


def _validate_postplan_contract_semantics(project_root: Path, selected: Component, operation: str) -> None:
    if selected.manager == "pip" and operation == "install":
        _validate_pip_requirements(project_root, selected.path, selected.manifests)


def _resolve_root(root: str | Path) -> Path:
    try:
        root_path = Path(root).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PackageContractError("invalid_project_root", "projectRoot could not be resolved") from exc
    try:
        if not root_path.is_dir():
            raise PackageContractError("invalid_project_root", "projectRoot must name an existing directory")
    except OSError as exc:
        raise PackageContractError("invalid_project_root", "projectRoot must name a readable directory") from exc
    return root_path


def _planning_error(
    exc: OperationError,
    graph: ProjectGraph,
    selector: str | None,
    operation: str,
) -> PackageContractError:
    message = str(exc)
    lowered = message.lower()
    details: dict[str, Any] = {"operation": operation}
    if "no supported project components" in lowered:
        code = "no_component"
    elif "multiple components" in lowered or "component selector" in lowered and "ambiguous" in lowered:
        code = "component_ambiguous"
        details["components"] = sorted(component.key(graph.root) for component in graph.components)
    elif "unknown component" in lowered:
        code = "component_not_found"
        if selector is not None:
            details["component"] = selector
    elif "component manifest is invalid" in lowered:
        code = "manifest_invalid"
    elif "multiple native lockfiles" in lowered or "multiple package managers" in lowered:
        code = "manager_ambiguous"
    elif "manifest declares" in lowered and "lockfile belongs" in lowered:
        code = "manager_conflict"
    elif "package manager is unknown" in lowered:
        code = "manager_unknown"
    elif "without a native lockfile" in lowered:
        code = "lock_required"
    elif "requires at least one package" in lowered:
        code = "packages_required"
    elif "does not accept package arguments" in lowered:
        code = "packages_forbidden"
    elif "--dev is only valid" in lowered or "development-dependency scope" in lowered:
        code = "dev_unsupported"
    elif "not supported for delegated operations" in lowered:
        code = "manager_unsupported"
    else:
        code = "operation_not_safe"
    return PackageContractError(code, message, details=details)


def plan_package_operation(
    root: str | Path,
    operation: str,
    *,
    component: str | None = None,
    packages: Sequence[str] = (),
    dev: bool = False,
) -> PackageOperationPlan:
    """Plan one native package operation without executing tools, writing state, or using network."""

    project_root = _resolve_root(root)
    operation = _validate_operation(operation)
    selector = _validate_selector(component)
    package_tuple = _validate_packages(packages)
    if not isinstance(dev, bool):
        raise PackageContractError("invalid_dev", "dev must be a boolean")

    try:
        graph = discover(project_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PackageContractError("discovery_failed", "project discovery could not be completed safely") from exc

    try:
        selected = select_component(graph, selector)
    except OperationError as exc:
        raise _planning_error(exc, graph, selector, operation) from exc

    _validate_portable_package_specs(selected.ecosystem, package_tuple)
    _validate_preplan_contract_semantics(selected, operation, package_tuple)

    try:
        command_plan = plan_operation(
            graph,
            operation,  # type: ignore[arg-type]
            selector=selected.key(graph.root),
            packages=package_tuple,
            dev=dev,
        )
    except OperationError as exc:
        raise _planning_error(exc, graph, selected.key(graph.root), operation) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise PackageContractError("planning_failed", "package operation planning could not be completed safely") from exc

    if command_plan.component != selected.key(graph.root):
        raise PackageContractError("planning_failed", "planned component does not match the selected project component")

    expected_ecosystem = SUPPORTED_MANAGER_ECOSYSTEMS.get(command_plan.manager)
    if expected_ecosystem != selected.ecosystem:
        raise PackageContractError(
            "manager_ecosystem_mismatch",
            "planned manager does not match the discovered component ecosystem",
        )

    _validate_postplan_contract_semantics(graph.root.resolve(), selected, operation)

    try:
        relative_cwd = command_plan.cwd.resolve().relative_to(graph.root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise PackageContractError(
            "external_mutation_scope",
            "planned working directory escapes the selected project root",
        ) from exc
    cwd = relative_cwd.as_posix() or "."

    return PackageOperationPlan(
        operation=operation,
        component=command_plan.component,
        ecosystem=selected.ecosystem,
        manager=command_plan.manager,
        cwd=cwd,
        packages=package_tuple,
        dev=dev,
        argv=tuple(command_plan.argv),
    )


def plan_package_operation_json(request: Mapping[str, object]) -> dict[str, Any]:
    """Structured JSON-compatible request/response entrypoint for embedding processes."""

    if not isinstance(request, Mapping):
        raise PackageContractError("invalid_request", "request must be a JSON object")
    allowed = {"requestSchemaVersion", "projectRoot", "operation", "component", "packages", "dev"}
    unknown = sorted(str(key) for key in request if key not in allowed)
    if unknown:
        raise PackageContractError("invalid_request", f"unknown request fields: {', '.join(unknown)}")
    request_schema = request.get("requestSchemaVersion")
    if type(request_schema) is not int or request_schema != REQUEST_SCHEMA_VERSION:
        raise PackageContractError("incompatible_request_schema", f"requestSchemaVersion must be {REQUEST_SCHEMA_VERSION}")
    if "projectRoot" not in request or "operation" not in request:
        raise PackageContractError("invalid_request", "projectRoot and operation are required")

    packages = request.get("packages", [])
    dev = request.get("dev", False)
    component = request.get("component")
    plan = plan_package_operation(
        request["projectRoot"],  # type: ignore[arg-type]
        request["operation"],  # type: ignore[arg-type]
        component=component,  # type: ignore[arg-type]
        packages=packages,  # type: ignore[arg-type]
        dev=dev,  # type: ignore[arg-type]
    )
    return plan.to_dict()


def error_response(error: PackageContractError) -> dict[str, Any]:
    return {**contract_metadata(), "ok": False, "error": error.to_dict()}
