from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .node_workspace import NodeWorkspaceError, inspect_node_workspace


class YarnGraphError(ValueError):
    """Raised when a safe Yarn Berry graph cannot be planned or decoded."""


@dataclass(frozen=True)
class YarnGraphPlan:
    component: str
    project_root: Path
    cwd: Path
    all_workspaces: bool
    selected_component: str | None = None

    @property
    def argv(self) -> tuple[str, ...]:
        args = ["yarn", "info"]
        if self.all_workspaces:
            args.append("--all")
        args.extend(("--recursive", "--virtuals", "--json"))
        return tuple(args)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "yarn",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "project_root": self.project_root.relative_to(root).as_posix() or ".",
            "argv": list(self.argv),
            "selected_component": self.selected_component,
            "source": "Yarn Berry stored lock resolutions via yarn info",
            "network": False,
            "project_mutation": False,
            "install_state": "temporary",
        }


@dataclass(frozen=True)
class YarnResolvedPackage:
    component: str
    locator: str
    name: str
    version: str | None
    reference: str
    protocol: str | None
    project_member: bool
    virtual: bool
    base_locator: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class YarnDependencyEdge:
    component: str
    source_locator: str
    target_locator: str
    descriptor: str
    kind: str = "dependency"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class YarnGraphResult:
    plan: YarnGraphPlan
    packages: list[YarnResolvedPackage]
    edges: list[YarnDependencyEdge]
    returncode: int
    yarn_version: str | None = None
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "yarn_version": self.yarn_version,
            "packages": [package.to_dict() for package in self.packages],
            "edges": [edge.to_dict() for edge in self.edges],
            "stderr": self.stderr,
        }


def _locator_parts(locator: str) -> tuple[str, str]:
    if locator.startswith("@"):
        slash = locator.find("/")
        if slash < 0:
            raise YarnGraphError(f"Invalid scoped Yarn locator {locator!r}.")
        separator = locator.find("@", slash)
    else:
        separator = locator.find("@")
    if separator <= 0:
        raise YarnGraphError(f"Invalid Yarn locator {locator!r}.")
    return locator[:separator], locator[separator + 1:]


def _protocol(reference: str) -> str | None:
    value = reference
    if value.startswith("virtual:"):
        marker = value.find("#")
        if marker >= 0:
            value = value[marker + 1:]
    separator = value.find(":")
    return value[:separator] if separator > 0 else None


def _base_locator(locator: str) -> str | None:
    name, reference = _locator_parts(locator)
    if not reference.startswith("virtual:"):
        return None
    marker = reference.find("#")
    if marker < 0 or marker + 1 >= len(reference):
        return None
    return f"{name}@{reference[marker + 1:]}"


def _declared_yarn_major(component: Component) -> int | None:
    value = component.metadata.get("package_manager_declared")
    if not isinstance(value, str) or not value.startswith("yarn@"):
        return None
    version = value[len("yarn@"):]
    match = re.search(r"\d+", version)
    return int(match.group(0)) if match else None


def _has_berry_lock(component: Component) -> bool:
    return component.manager == "yarn" and "yarn.lock" in component.lockfiles and (_declared_yarn_major(component) or 0) >= 2


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _workspace_owners(graph: ProjectGraph) -> tuple[dict[Path, Component], dict[Path, Component]]:
    roots: dict[Path, Component] = {}
    members: dict[Path, Component] = {}
    for component in graph.components:
        if component.ecosystem != "node" or not _has_berry_lock(component):
            continue
        try:
            workspace = inspect_node_workspace(component.path)
        except NodeWorkspaceError as exc:
            raise YarnGraphError(str(exc)) from exc
        if workspace is None or workspace.manager not in {None, "yarn"}:
            continue
        root_path = component.path.resolve()
        roots[root_path] = component
        for member in workspace.members:
            path = member.path.resolve()
            existing = members.get(path)
            if existing is not None and existing.path.resolve() != root_path:
                raise YarnGraphError(
                    f"Node component {path} is claimed by multiple Yarn workspace roots: "
                    f"{existing.path} and {component.path}."
                )
            members[path] = component
    return roots, members


def plan_yarn_graphs(graph: ProjectGraph, selector: str | None = None) -> list[YarnGraphPlan]:
    node_components = [component for component in graph.components if component.ecosystem == "node"]
    _roots, member_owners = _workspace_owners(graph)

    if selector is not None:
        matches = [component for component in node_components if _matches(component, graph, selector)]
        if not matches:
            return []
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise YarnGraphError(f"Component selector '{selector}' is ambiguous for Yarn graph ingestion: {choices}")
        selected = matches[0]
        owner = member_owners.get(selected.path.resolve())
        if owner is not None:
            return [YarnGraphPlan(
                owner.key(graph.root), owner.path, selected.path,
                all_workspaces=False,
                selected_component=selected.key(graph.root),
            )]
        if _has_berry_lock(selected):
            return [YarnGraphPlan(
                selected.key(graph.root), selected.path, selected.path,
                all_workspaces=False,
                selected_component=selected.key(graph.root),
            )]
        return []

    plans: list[YarnGraphPlan] = []
    for component in node_components:
        path = component.path.resolve()
        if path in member_owners:
            continue
        if not _has_berry_lock(component):
            continue
        plans.append(YarnGraphPlan(component.key(graph.root), component.path, component.path, all_workspaces=True))
    plans.sort(key=lambda plan: plan.project_root.relative_to(graph.root).as_posix())
    return plans


def yarn_provider_component_keys(
    graph: ProjectGraph,
    plans: Iterable[YarnGraphPlan] | None = None,
) -> set[str]:
    selected = tuple(plans) if plans is not None else tuple(plan_yarn_graphs(graph))
    if not selected:
        return set()
    _roots, member_owners = _workspace_owners(graph)
    by_path = {component.path.resolve(): component for component in graph.components if component.ecosystem == "node"}
    result: set[str] = set()
    for plan in selected:
        result.add(plan.component)
        if plan.selected_component is not None:
            result.add(plan.selected_component)
            continue
        owner_path = plan.project_root.resolve()
        for member_path, owner in member_owners.items():
            if owner.path.resolve() != owner_path:
                continue
            component = by_path.get(member_path)
            if component is not None:
                result.add(component.key(graph.root))
    return result


def parse_yarn_info(text: str, component: str) -> tuple[list[YarnResolvedPackage], list[YarnDependencyEdge]]:
    packages: dict[str, YarnResolvedPackage] = {}
    raw_dependencies: dict[str, list[dict[str, Any]]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise YarnGraphError(f"Could not parse Yarn info JSON line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise YarnGraphError(f"Yarn info JSON line {line_number} is not an object.")
        locator = record.get("value")
        children = record.get("children")
        if not isinstance(locator, str) or not isinstance(children, dict):
            raise YarnGraphError(f"Yarn info JSON line {line_number} lacks locator/children fields.")
        name, reference = _locator_parts(locator)
        version = children.get("Version") if isinstance(children.get("Version"), str) else None
        protocol = _protocol(reference)
        virtual = reference.startswith("virtual:")
        package = YarnResolvedPackage(
            component=component,
            locator=locator,
            name=name,
            version=version,
            reference=reference,
            protocol=protocol,
            project_member=protocol == "workspace",
            virtual=virtual,
            base_locator=_base_locator(locator),
        )
        packages[locator] = package
        dependencies = children.get("Dependencies")
        peer_dependencies = children.get("Peer dependencies")
        values: list[dict[str, Any]] = []
        if isinstance(dependencies, list):
            values.extend(item for item in dependencies if isinstance(item, dict))
        if isinstance(peer_dependencies, list):
            values.extend(item for item in peer_dependencies if isinstance(item, dict))
        raw_dependencies[locator] = values

    edges: list[YarnDependencyEdge] = []
    for source, dependencies in raw_dependencies.items():
        for dependency in dependencies:
            descriptor = dependency.get("descriptor")
            target = dependency.get("locator")
            if not isinstance(descriptor, str) or not isinstance(target, str):
                continue
            edges.append(YarnDependencyEdge(component, source, target, descriptor, "dependency"))

    # Berry may resolve a parent dependency to a virtual locator while the
    # virtual record only exposes peer-specific information. Link the virtual
    # occurrence to its devirtualized package, whose normal dependency list is
    # emitted separately by `yarn info`.
    for package in packages.values():
        if package.virtual and package.base_locator and package.base_locator in packages:
            edges.append(YarnDependencyEdge(
                component, package.locator, package.base_locator, package.name, "devirtualized",
            ))

    package_list = sorted(packages.values(), key=lambda item: (item.name.lower(), item.version or "", item.locator))
    edges = sorted(
        {(edge.source_locator, edge.target_locator, edge.descriptor, edge.kind): edge for edge in edges}.values(),
        key=lambda item: (item.source_locator, item.target_locator, item.descriptor, item.kind),
    )
    return package_list, edges


def _major(version: str) -> int | None:
    match = re.match(r"\s*(\d+)", version)
    return int(match.group(1)) if match else None


def execute_yarn_graph(
    plan: YarnGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> YarnGraphResult:
    executable = which("yarn")
    if executable is None:
        return YarnGraphResult(plan, [], [], 127, stderr="Executable 'yarn' is not available on PATH.")

    base_env = os.environ.copy()
    base_env.update({
        "YARN_ENABLE_NETWORK": "0",
        "YARN_ENABLE_HARDENED_MODE": "0",
        "YARN_ENABLE_TELEMETRY": "0",
        "YARN_ENABLE_IMMUTABLE_CACHE": "1",
        "YARN_ENABLE_COLORS": "0",
    })
    try:
        version_result = run(
            [executable, "--version"], cwd=plan.cwd, env=base_env,
            text=True, capture_output=True, check=False,
        )
    except OSError as exc:
        return YarnGraphResult(plan, [], [], 127, stderr=str(exc))
    yarn_version = (version_result.stdout or "").strip()
    if version_result.returncode != 0:
        return YarnGraphResult(
            plan, [], [], version_result.returncode,
            yarn_version=yarn_version or None,
            stderr=(version_result.stderr or version_result.stdout or "").strip(),
        )
    major = _major(yarn_version)
    if major is None or major < 2:
        return YarnGraphResult(
            plan, [], [], 2, yarn_version=yarn_version or None,
            stderr=f"Yarn Berry 2+ is required for native graph ingestion; resolved Yarn version is {yarn_version or 'unknown'}.",
        )

    with tempfile.TemporaryDirectory(prefix="upm-yarn-state-") as temporary:
        env = dict(base_env)
        env["YARN_INSTALL_STATE_PATH"] = str(Path(temporary) / "install-state.gz")
        try:
            completed = run(
                [executable, *plan.argv[1:]], cwd=plan.cwd, env=env,
                text=True, capture_output=True, check=False,
            )
        except OSError as exc:
            return YarnGraphResult(plan, [], [], 127, yarn_version=yarn_version, stderr=str(exc))

    if completed.returncode != 0:
        return YarnGraphResult(
            plan, [], [], completed.returncode, yarn_version=yarn_version,
            stderr=(completed.stderr or completed.stdout or "").strip(),
        )
    try:
        packages, edges = parse_yarn_info(completed.stdout or "", plan.component)
    except YarnGraphError as exc:
        return YarnGraphResult(plan, [], [], 1, yarn_version=yarn_version, stderr=str(exc))
    return YarnGraphResult(
        plan, packages, edges, 0, yarn_version=yarn_version,
        stderr=(completed.stderr or "").strip(),
    )
