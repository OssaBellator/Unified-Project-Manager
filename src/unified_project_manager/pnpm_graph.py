from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph
from .pnpm_workspace import find_pnpm_workspace_root


class PnpmGraphError(ValueError):
    """Raised when an authoritative pnpm lock-backed graph cannot be queried safely."""


@dataclass(frozen=True)
class PnpmGraphPlan:
    component: str
    cwd: Path
    recursive: bool = False

    @property
    def argv(self) -> tuple[str, ...]:
        recursive = ("-r",) if self.recursive else ()
        return ("pnpm", "list", *recursive, "--depth", "Infinity", "--json", "--lockfile-only")

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "pnpm",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "argv": list(self.argv),
            "source": "pnpm-lock.yaml via pnpm list --lockfile-only",
            "network": False,
            "mutates_project": False,
            "recursive": self.recursive,
        }


@dataclass(frozen=True)
class PnpmProject:
    component: str
    ref: str
    path: str
    name: str | None
    version: str | None
    private: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PnpmLogicalPackage:
    component: str
    project_ref: str
    ref: str
    alias: str
    name: str
    version: str | None
    parent_ref: str
    depth: int
    direct: bool
    scope: str
    resolved: str | None = None
    path: str | None = None
    deduped: bool = False
    deduped_dependencies_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PnpmLogicalEdge:
    component: str
    project_ref: str
    source_ref: str
    target_ref: str
    dependency_alias: str
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PnpmGraphResult:
    plan: PnpmGraphPlan
    projects: list[PnpmProject]
    packages: list[PnpmLogicalPackage]
    edges: list[PnpmLogicalEdge]
    returncode: int
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(root),
            "succeeded": self.succeeded,
            "returncode": self.returncode,
            "projects": [project.to_dict() for project in self.projects],
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


def _plan_for_component(graph: ProjectGraph, component: Component) -> PnpmGraphPlan | None:
    workspace_root = find_pnpm_workspace_root(component.path, graph.root)
    by_path = {
        item.path.resolve(): item
        for item in graph.components
        if item.ecosystem == "node"
    }
    if workspace_root is not None:
        owner = by_path.get(workspace_root.resolve())
        if owner is None or owner.manager != "pnpm" or not (workspace_root / "pnpm-lock.yaml").is_file():
            return None
        return PnpmGraphPlan(owner.key(graph.root), workspace_root, recursive=True)
    if component.manager == "pnpm" and "pnpm-lock.yaml" in component.lockfiles:
        return PnpmGraphPlan(component.key(graph.root), component.path, recursive=False)
    return None


def plan_pnpm_graphs(graph: ProjectGraph, selector: str | None = None) -> list[PnpmGraphPlan]:
    node_components = [component for component in graph.components if component.ecosystem == "node"]
    if selector is not None:
        matches = [component for component in node_components if _matches(component, graph, selector)]
        if len(matches) > 1:
            choices = ", ".join(component.key(graph.root) for component in matches)
            raise PnpmGraphError(f"Component selector '{selector}' is ambiguous for pnpm graph ingestion: {choices}")
        if not matches:
            return []
        plan = _plan_for_component(graph, matches[0])
        return [plan] if plan is not None else []

    unique: dict[Path, PnpmGraphPlan] = {}
    for component in node_components:
        plan = _plan_for_component(graph, component)
        if plan is not None:
            unique.setdefault(plan.cwd.resolve(), plan)
    return [unique[path] for path in sorted(unique, key=str)]


def pnpm_provider_component_keys(
    graph: ProjectGraph,
    plans: Iterable[PnpmGraphPlan] | None = None,
) -> set[str]:
    """Return every component whose relationship evidence is owned by the plans.

    A recursive pnpm workspace plan owns the workspace root and every discovered
    Node component nested under that exact `pnpm-workspace.yaml` root. This keeps
    capability/skip accounting aligned with selector planning: a member can be
    served by the authoritative root even when the member has no manager or lock.
    """
    selected = tuple(plans) if plans is not None else tuple(plan_pnpm_graphs(graph))
    if not selected:
        return set()
    by_root = {plan.cwd.resolve(): plan for plan in selected}
    result: set[str] = set()
    for component in graph.components:
        if component.ecosystem != "node":
            continue
        component_path = component.path.resolve()
        direct = by_root.get(component_path)
        if direct is not None:
            result.add(component.key(graph.root))
            continue
        workspace_root = find_pnpm_workspace_root(component.path, graph.root)
        if workspace_root is None:
            continue
        owner_plan = by_root.get(workspace_root.resolve())
        if owner_plan is not None and owner_plan.recursive:
            result.add(component.key(graph.root))
    return result


def _project_ref(component: str, index: int, path: str) -> str:
    return f"{component}:project:{index}:{path}"


def _node_ref(parent_ref: str, alias: str, version: str | None, ordinal: int) -> str:
    return f"{parent_ref}>{alias}@{version or '?'}#{ordinal}"


def parse_pnpm_list(
    text: str,
    component: str,
    cwd: Path,
) -> tuple[list[PnpmProject], list[PnpmLogicalPackage], list[PnpmLogicalEdge]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PnpmGraphError(f"Could not parse pnpm list JSON: {exc}") from exc
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise PnpmGraphError("pnpm list JSON root must be an object or array.")

    projects: list[PnpmProject] = []
    packages: list[PnpmLogicalPackage] = []
    edges: list[PnpmLogicalEdge] = []
    root_fields = (
        ("dependencies", "runtime"),
        ("devDependencies", "development"),
        ("optionalDependencies", "optional"),
        ("unsavedDependencies", "unsaved"),
    )

    for project_index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        raw_path = record.get("path")
        project_path = Path(raw_path) if isinstance(raw_path, str) and raw_path else cwd
        if not project_path.is_absolute():
            project_path = (cwd / project_path).resolve()
        else:
            project_path = project_path.resolve()
        try:
            relative_path = project_path.relative_to(cwd).as_posix() or "."
        except ValueError:
            relative_path = str(project_path)
        project_ref = _project_ref(component, project_index, relative_path)
        project = PnpmProject(
            component=component,
            ref=project_ref,
            path=relative_path,
            name=record.get("name") if isinstance(record.get("name"), str) else None,
            version=record.get("version") if isinstance(record.get("version"), str) else None,
            private=bool(record.get("private")),
        )
        projects.append(project)

        def visit(dependencies: object, parent_ref: str, depth: int, scope: str) -> None:
            if not isinstance(dependencies, dict):
                return
            for ordinal, alias in enumerate(sorted(dependencies), start=1):
                value = dependencies[alias]
                if not isinstance(alias, str) or not isinstance(value, dict):
                    continue
                name = value.get("from") if isinstance(value.get("from"), str) else alias
                version = value.get("version") if isinstance(value.get("version"), str) else None
                child_ref = _node_ref(parent_ref, alias, version, ordinal)
                deduped_count = value.get("dedupedDependenciesCount")
                if not isinstance(deduped_count, int) or isinstance(deduped_count, bool) or deduped_count < 0:
                    deduped_count = 0
                package = PnpmLogicalPackage(
                    component=component,
                    project_ref=project_ref,
                    ref=child_ref,
                    alias=alias,
                    name=name,
                    version=version,
                    parent_ref=parent_ref,
                    depth=depth,
                    direct=depth == 1,
                    scope=scope,
                    resolved=value.get("resolved") if isinstance(value.get("resolved"), str) else None,
                    path=value.get("path") if isinstance(value.get("path"), str) else None,
                    deduped=bool(value.get("deduped")),
                    deduped_dependencies_count=deduped_count,
                )
                packages.append(package)
                edges.append(PnpmLogicalEdge(component, project_ref, parent_ref, child_ref, alias, scope))
                visit(value.get("dependencies"), child_ref, depth + 1, scope)

        for field, scope in root_fields:
            visit(record.get(field), project_ref, 1, scope)

    projects.sort(key=lambda item: (item.path, item.name or "", item.version or ""))
    packages.sort(key=lambda item: (item.project_ref, item.ref))
    edges.sort(key=lambda item: (item.project_ref, item.source_ref, item.target_ref))
    return projects, packages, edges


def execute_pnpm_graph(
    plan: PnpmGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> PnpmGraphResult:
    executable = which("pnpm")
    if executable is None:
        return PnpmGraphResult(plan, [], [], [], 127, stderr="Executable 'pnpm' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return PnpmGraphResult(plan, [], [], [], 127, stderr=str(exc))

    output = completed.stdout or ""
    if not output.strip():
        return PnpmGraphResult(
            plan, [], [], [], completed.returncode or 1,
            stderr=(completed.stderr or "pnpm list produced no JSON output").strip(),
        )
    try:
        projects, packages, edges = parse_pnpm_list(output, plan.component, plan.cwd)
    except PnpmGraphError as exc:
        return PnpmGraphResult(plan, [], [], [], completed.returncode or 1, stderr=str(exc))
    return PnpmGraphResult(
        plan=plan,
        projects=projects,
        packages=packages,
        edges=edges,
        returncode=completed.returncode,
        stderr=(completed.stderr or "").strip(),
    )
