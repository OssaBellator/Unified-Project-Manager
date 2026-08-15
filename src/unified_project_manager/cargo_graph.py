from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class CargoGraphError(ValueError):
    """Raised when an authoritative Cargo dependency graph cannot be queried safely."""


@dataclass(frozen=True)
class CargoGraphPlan:
    component: str
    cwd: Path
    argv: tuple[str, ...] = (
        "cargo", "metadata", "--format-version", "1", "--locked", "--offline"
    )

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "rust",
            "manager": "cargo",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "argv": list(self.argv),
            "network": False,
            "lockfile_mutation": False,
        }


@dataclass(frozen=True)
class CargoPackage:
    component: str
    package_id: str
    name: str
    version: str
    source: str | None
    manifest_path: str | None
    workspace_member: bool
    workspace_default_member: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CargoDependencyEdge:
    component: str
    source_id: str
    target_id: str
    dependency_name: str
    kinds: tuple[str, ...]
    targets: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CargoGraphResult:
    plan: CargoGraphPlan
    packages: list[CargoPackage]
    edges: list[CargoDependencyEdge]
    returncode: int
    resolve_root: str | None = None
    workspace_root: str | None = None
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "resolve_root": self.resolve_root,
            "workspace_root": self.workspace_root,
            "packages": [package.to_dict() for package in self.packages],
            "edges": [edge.to_dict() for edge in self.edges],
            "stderr": self.stderr,
        }


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _inside_known_workspace(component: Component, graph: ProjectGraph) -> bool:
    for candidate in graph.components:
        if candidate is component or candidate.ecosystem != "rust":
            continue
        if not candidate.metadata.get("workspace"):
            continue
        try:
            component.path.relative_to(candidate.path)
        except ValueError:
            continue
        return True
    return False


def plan_cargo_graphs(graph: ProjectGraph, selector: str | None = None) -> list[CargoGraphPlan]:
    candidates = [
        component
        for component in graph.components
        if component.ecosystem == "rust"
        and component.manager == "cargo"
        and "Cargo.lock" in component.lockfiles
        and not _inside_known_workspace(component, graph)
    ]
    if selector is not None:
        direct = [component for component in graph.components if component.ecosystem == "rust" and _matches(component, graph, selector)]
        if len(direct) > 1:
            choices = ", ".join(component.key(graph.root) for component in direct)
            raise CargoGraphError(f"Component selector '{selector}' is ambiguous for Cargo graph ingestion: {choices}")
        if direct:
            selected = direct[0]
            if _inside_known_workspace(selected, graph):
                owners = [
                    component for component in graph.components
                    if component.ecosystem == "rust" and component.metadata.get("workspace")
                    and selected.path != component.path
                    and _is_relative_to(selected.path, component.path)
                ]
                if owners:
                    selected = min(owners, key=lambda item: len(item.path.parts))
            candidates = [selected] if selected in candidates or "Cargo.lock" in selected.lockfiles else []
        else:
            candidates = []
    return [CargoGraphPlan(component.key(graph.root), component.path) for component in candidates]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def parse_cargo_metadata(text: str, component: str) -> tuple[list[CargoPackage], list[CargoDependencyEdge], str | None, str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CargoGraphError(f"Could not parse cargo metadata JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CargoGraphError("cargo metadata JSON root is not an object.")

    workspace_members = {value for value in data.get("workspace_members", []) if isinstance(value, str)}
    default_members = {value for value in data.get("workspace_default_members", []) if isinstance(value, str)}
    packages: list[CargoPackage] = []
    for record in data.get("packages", []):
        if not isinstance(record, dict):
            continue
        package_id = record.get("id")
        name = record.get("name")
        version = record.get("version")
        if not all(isinstance(value, str) and value for value in (package_id, name, version)):
            continue
        packages.append(CargoPackage(
            component=component,
            package_id=package_id,
            name=name,
            version=version,
            source=record.get("source") if isinstance(record.get("source"), str) else None,
            manifest_path=record.get("manifest_path") if isinstance(record.get("manifest_path"), str) else None,
            workspace_member=package_id in workspace_members,
            workspace_default_member=package_id in default_members,
        ))

    edges: list[CargoDependencyEdge] = []
    resolve = data.get("resolve")
    resolve_root = None
    if isinstance(resolve, dict):
        resolve_root = resolve.get("root") if isinstance(resolve.get("root"), str) else None
        for node in resolve.get("nodes", []):
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                continue
            source_id = node["id"]
            deps = node.get("deps")
            if isinstance(deps, list):
                for dep in deps:
                    if not isinstance(dep, dict) or not isinstance(dep.get("pkg"), str):
                        continue
                    name = dep.get("name") if isinstance(dep.get("name"), str) else dep["pkg"]
                    kinds: set[str] = set()
                    targets: set[str] = set()
                    for kind in dep.get("dep_kinds", []) if isinstance(dep.get("dep_kinds"), list) else []:
                        if not isinstance(kind, dict):
                            continue
                        value = kind.get("kind")
                        kinds.add(value if isinstance(value, str) and value else "normal")
                        target = kind.get("target")
                        if isinstance(target, str) and target:
                            targets.add(target)
                    edges.append(CargoDependencyEdge(
                        component=component,
                        source_id=source_id,
                        target_id=dep["pkg"],
                        dependency_name=name,
                        kinds=tuple(sorted(kinds)) or ("normal",),
                        targets=tuple(sorted(targets)),
                    ))
            elif isinstance(node.get("dependencies"), list):
                for target in node["dependencies"]:
                    if isinstance(target, str):
                        edges.append(CargoDependencyEdge(component, source_id, target, target, ("unknown",), ()))

    workspace_root = data.get("workspace_root") if isinstance(data.get("workspace_root"), str) else None
    packages.sort(key=lambda item: (not item.workspace_member, item.name, item.version, item.package_id))
    edges.sort(key=lambda item: (item.source_id, item.dependency_name, item.target_id, item.kinds, item.targets))
    return packages, edges, resolve_root, workspace_root


def execute_cargo_graph(
    plan: CargoGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> CargoGraphResult:
    executable = which("cargo")
    if executable is None:
        return CargoGraphResult(plan, [], [], 127, stderr="Executable 'cargo' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return CargoGraphResult(plan, [], [], 127, stderr=str(exc))
    if completed.returncode != 0:
        return CargoGraphResult(
            plan,
            [],
            [],
            completed.returncode,
            stderr=(completed.stderr or completed.stdout or "").strip(),
        )
    try:
        packages, edges, resolve_root, workspace_root = parse_cargo_metadata(completed.stdout or "", plan.component)
    except CargoGraphError as exc:
        return CargoGraphResult(plan, [], [], 1, stderr=str(exc))
    return CargoGraphResult(plan, packages, edges, 0, resolve_root, workspace_root, (completed.stderr or "").strip())
