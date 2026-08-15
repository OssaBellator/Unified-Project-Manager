from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .models import ProjectGraph
from .native_exec import NativeExecError, NativeExecPlan, plan_native_exec
from .operations import OperationError, select_component


class UpdateOperationError(ValueError):
    """Raised when an update cannot be mapped safely to native manager semantics."""


@dataclass(frozen=True)
class UpdatePlan:
    native: NativeExecPlan
    packages: tuple[str, ...]
    update_scope: str
    manifest_may_change: bool
    native_state_may_change: bool
    installed_state_may_change: bool
    network_may_be_used: bool
    semantics: str

    @property
    def component(self) -> str:
        return self.native.component

    @property
    def manager(self) -> str:
        return self.native.manager

    @property
    def cwd(self):
        return self.native.cwd

    @property
    def argv(self) -> tuple[str, ...]:
        return self.native.argv

    def to_dict(self, root) -> dict[str, Any]:
        return {
            **self.native.to_dict(root),
            "packages": list(self.packages),
            "update_scope": self.update_scope,
            "manifest_may_change": self.manifest_may_change,
            "native_state_may_change": self.native_state_may_change,
            "installed_state_may_change": self.installed_state_may_change,
            "network_may_be_used": self.network_may_be_used,
            "semantics": self.semantics,
        }


def _yarn_major(component) -> int | None:
    declared = component.metadata.get("package_manager_declared")
    if not isinstance(declared, str) or not declared.startswith("yarn@"):
        return None
    text = declared.removeprefix("yarn@").split("-", 1)[0]
    try:
        return int(text.split(".", 1)[0])
    except ValueError:
        return None


def _arguments(manager: str, component, packages: tuple[str, ...]) -> tuple[tuple[str, ...], dict[str, Any]]:
    selected = bool(packages)
    scope = "selected" if selected else "all"

    if manager == "npm":
        return (
            ("update", *packages),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="updates npm dependency resolutions within declared semver ranges; package.json ranges are not intentionally rewritten",
            ),
        )

    if manager == "pnpm":
        return (
            ("update", *packages),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="updates pnpm dependency resolutions within the project's declared dependency constraints",
            ),
        )

    if manager == "yarn":
        major = _yarn_major(component)
        if major is not None and major <= 1:
            return (
                ("upgrade", *packages),
                dict(
                    update_scope=scope,
                    manifest_may_change=True,
                    native_state_may_change=True,
                    installed_state_may_change=True,
                    network_may_be_used=True,
                    semantics="uses Yarn Classic upgrade semantics",
                ),
            )
        patterns = packages or ("*",)
        return (
            ("up", *patterns),
            dict(
                update_scope=scope,
                manifest_may_change=True,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="uses modern Yarn up semantics; all-dependency updates pass '*' as a Yarn pattern without shell expansion",
            ),
        )

    if manager == "bun":
        return (
            ("update", *packages),
            dict(
                update_scope=scope,
                manifest_may_change=True,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="uses Bun's native dependency update operation",
            ),
        )

    if manager == "uv":
        if packages:
            arguments: list[str] = ["lock"]
            for package in packages:
                arguments.extend(("--upgrade-package", package))
        else:
            arguments = ["lock", "--upgrade"]
        return (
            tuple(arguments),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=False,
                network_may_be_used=True,
                semantics="upgrades uv.lock resolution; installed environment synchronization remains a separate explicit operation",
            ),
        )

    if manager == "poetry":
        return (
            ("update", *packages),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="uses Poetry's native update operation against project constraints",
            ),
        )

    if manager == "pdm":
        return (
            ("update", *packages),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=True,
                network_may_be_used=True,
                semantics="uses PDM's native update operation against project constraints",
            ),
        )

    if manager == "cargo":
        if packages:
            arguments = ["update"]
            for package in packages:
                arguments.extend(("-p", package))
        else:
            arguments = ["update"]
        return (
            tuple(arguments),
            dict(
                update_scope=scope,
                manifest_may_change=False,
                native_state_may_change=True,
                installed_state_may_change=False,
                network_may_be_used=True,
                semantics="updates Cargo.lock selections while respecting Cargo.toml requirements",
            ),
        )

    if manager == "go":
        if not packages:
            raise UpdateOperationError(
                "Go updates require explicit module/package targets; UPM refuses to invent a repository-wide 'go get -u ./...' policy."
            )
        targets = tuple(package if "@" in package else f"{package}@latest" for package in packages)
        return (
            ("get", *targets),
            dict(
                update_scope="selected",
                manifest_may_change=True,
                native_state_may_change=True,
                installed_state_may_change=False,
                network_may_be_used=True,
                semantics="uses explicit go get targets; targets without @version are upgraded to @latest",
            ),
        )

    if manager == "pip":
        raise UpdateOperationError(
            "pip cannot safely update project desired state by itself; use a pyproject-aware manager or an explicit native workflow."
        )

    raise UpdateOperationError(f"Update planning is not configured for manager '{manager}'.")


def plan_update(
    graph: ProjectGraph,
    *,
    selector: str | None = None,
    packages: Sequence[str] = (),
) -> UpdatePlan:
    package_tuple = tuple(str(item) for item in packages)
    if any(not item for item in package_tuple):
        raise UpdateOperationError("Update package targets must be non-empty strings.")
    try:
        component = select_component(graph, selector)
    except OperationError as exc:
        raise UpdateOperationError(str(exc)) from exc
    manager = component.manager
    if manager is None:
        raise UpdateOperationError("Cannot update because the component's authoritative manager is unknown.")
    arguments, metadata = _arguments(manager, component, package_tuple)
    try:
        native = plan_native_exec(graph, arguments, selector=component.key(graph.root))
    except NativeExecError as exc:
        raise UpdateOperationError(str(exc)) from exc
    return UpdatePlan(native=native, packages=package_tuple, **metadata)
