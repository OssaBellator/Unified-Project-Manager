from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .node_workspace import NodeWorkspaceError, inspect_node_workspace


class NpmGraphError(ValueError):
    """Raised when an authoritative npm logical dependency graph cannot be queried safely."""


@dataclass(frozen=True)
class NpmGraphPlan:
    component: str
    cwd: Path
    workspace_selector: str | None = None

    @property
    def argv(self) -> tuple[str, ...]:
        args: list[str] = ["npm", "ls", "--all", "--json", "--package-lock-only"]
        if self.workspace_selector:
            args.extend(("--workspace", self.workspace_selector))
        return tuple(args)

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "npm",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "argv": list(self.argv),
            "source": "package-lock",
            "network": False,
            "mutates_project": False,
            "workspace_selector": self.workspace_selector,
        }


@dataclass(frozen=True)
class NpmLogicalPackage:
    component: str
    ref: str
    name: str
    version: str | None
    parent_ref: str | None
    depth: int
    direct: bool
    overridden: bool = False
    resolved: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NpmLogicalEdge:
    component: str
    source_ref: str
    target_ref: str
    dependency_name: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NpmGraphResult:
    plan: NpmGraphPlan
    packages: list[NpmLogicalPackage]
    edges: list[NpmLogicalEdge]
    returncode: int
    root_name: str | None = None
    root_version: str | None = None
    problems: tuple[str, ...] = ()
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "root": {"name": self.root_name, "version": self.root_version},
            "packages": [package.to_dict() for package in self.packages],
            "edges": [edge.to_dict() for edge in self.edges],
            "problems": list(self.problems),
            "stderr": self.stderr,
        }


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _has_npm_lock(component: Component) -> bool:
    return component.manager == "npm" and any(
        name in component.lockfiles for name in ("package-lock.json", "npm-shrinkwrap.json")
    )


def _workspace_owners(graph: ProjectGraph) -> tuple[dict[Path, Component], dict[Path, Component]]:
    """Return npm workspace roots and exact member->root ownership."""
    roots: dict[Path, Component] = {}
    members: dict[Path, Component] = {}
    for component in graph.components:
        if component.ecosystem != "node" or not _has_npm_lock(component):
            continue
        try:
            workspace = inspect_node_workspace(component.path)
        except NodeWorkspaceError as exc:
            raise NpmGraphError(str(exc)) from exc
        if workspace is None or workspace.manager not in {None, "npm"}:
            continue
        root_path = component.path.resolve()
        roots[root_path] = component
        for member in workspace.members:
            path = member.path.resolve()
            existing = members.get(path)
            if existing is not None and existing.path.resolve() != root_path:
                raise NpmGraphError(
                    f"Node component {path} is claimed by multiple npm workspace roots: "
                    f"{existing.path} and {component.path}."
                )
            members[path] = component
    return roots, members


def _workspace_selector(member: Component, owner: Component) -> str:
    relative = member.path.resolve().relative_to(owner.path.resolve()).as_posix() or "."
    return "." if relative == "." else f"./{relative}"


def plan_npm_graphs(graph: ProjectGraph, selector: str | None = None) -> list[NpmGraphPlan]:
    node_components = [component for component in graph.components if component.ecosystem == "node"]
    roots, member_owners = _workspace_owners(graph)

    if selector is not None:
        matches = [component for component in node_components if _matches(component, graph, selector)]
        if not matches:
            return []
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise NpmGraphError(f"Component selector '{selector}' is ambiguous for npm graph ingestion: {choices}")
        selected = matches[0]
        owner = member_owners.get(selected.path.resolve())
        if owner is not None:
            return [NpmGraphPlan(
                owner.key(graph.root),
                owner.path,
                workspace_selector=_workspace_selector(selected, owner),
            )]
        if _has_npm_lock(selected):
            return [NpmGraphPlan(selected.key(graph.root), selected.path)]
        return []

    plans: list[NpmGraphPlan] = []
    for component in node_components:
        path = component.path.resolve()
        if path in member_owners:
            continue
        if not _has_npm_lock(component):
            continue
        plans.append(NpmGraphPlan(component.key(graph.root), component.path))
    plans.sort(key=lambda plan: plan.cwd.relative_to(graph.root).as_posix())
    return plans


def npm_provider_component_keys(
    graph: ProjectGraph,
    plans: Iterable[NpmGraphPlan] | None = None,
) -> set[str]:
    """Return all discovered components served by the selected npm root plans."""
    selected = tuple(plans) if plans is not None else tuple(plan_npm_graphs(graph))
    if not selected:
        return set()
    planned_roots = {plan.cwd.resolve(): plan for plan in selected}
    _roots, member_owners = _workspace_owners(graph)
    result: set[str] = set()
    for component in graph.components:
        if component.ecosystem != "node":
            continue
        path = component.path.resolve()
        if path in planned_roots:
            result.add(component.key(graph.root))
            continue
        owner = member_owners.get(path)
        if owner is not None and owner.path.resolve() in planned_roots:
            result.add(component.key(graph.root))
    return result


def _ref(parent_ref: str, name: str, version: str | None, ordinal: int) -> str:
    rendered_version = version or "?"
    return f"{parent_ref}>{name}@{rendered_version}#{ordinal}"


def parse_npm_ls(text: str, component: str) -> tuple[str | None, str | None, list[NpmLogicalPackage], list[NpmLogicalEdge], tuple[str, ...]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NpmGraphError(f"Could not parse npm ls JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NpmGraphError("npm ls JSON root is not an object.")

    root_name = data.get("name") if isinstance(data.get("name"), str) else None
    root_version = data.get("version") if isinstance(data.get("version"), str) else None
    root_ref = f"{component}:root"
    packages: list[NpmLogicalPackage] = []
    edges: list[NpmLogicalEdge] = []

    def visit(dependencies: object, parent_ref: str, depth: int) -> None:
        if not isinstance(dependencies, dict):
            return
        for ordinal, name in enumerate(sorted(dependencies), start=1):
            record = dependencies[name]
            if not isinstance(record, dict):
                continue
            version = record.get("version") if isinstance(record.get("version"), str) else None
            current_ref = _ref(parent_ref, name, version, ordinal)
            packages.append(NpmLogicalPackage(
                component=component,
                ref=current_ref,
                name=name,
                version=version,
                parent_ref=parent_ref,
                depth=depth,
                direct=depth == 1,
                overridden=bool(record.get("overridden")),
                resolved=record.get("resolved") if isinstance(record.get("resolved"), str) else None,
            ))
            edges.append(NpmLogicalEdge(component, parent_ref, current_ref, name))
            visit(record.get("dependencies"), current_ref, depth + 1)

    visit(data.get("dependencies"), root_ref, 1)
    problems = tuple(value for value in data.get("problems", []) if isinstance(value, str))
    return root_name, root_version, packages, edges, problems


def execute_npm_graph(
    plan: NpmGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> NpmGraphResult:
    executable = which("npm")
    if executable is None:
        return NpmGraphResult(plan, [], [], 127, stderr="Executable 'npm' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return NpmGraphResult(plan, [], [], 127, stderr=str(exc))
    stdout = completed.stdout or ""
    try:
        root_name, root_version, packages, edges, problems = parse_npm_ls(stdout, plan.component)
    except NpmGraphError as exc:
        return NpmGraphResult(plan, [], [], completed.returncode or 1, stderr=str(exc))
    stderr = (completed.stderr or "").strip()
    if problems and not stderr:
        stderr = "; ".join(problems)
    return NpmGraphResult(
        plan,
        packages,
        edges,
        completed.returncode,
        root_name=root_name,
        root_version=root_version,
        problems=problems,
        stderr=stderr,
    )
