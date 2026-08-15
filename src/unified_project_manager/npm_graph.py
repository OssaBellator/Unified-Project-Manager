from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class NpmGraphError(ValueError):
    """Raised when an authoritative npm logical dependency graph cannot be queried safely."""


@dataclass(frozen=True)
class NpmGraphPlan:
    component: str
    cwd: Path
    argv: tuple[str, ...] = ("npm", "ls", "--all", "--json", "--package-lock-only")

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": "node",
            "manager": "npm",
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "argv": list(self.argv),
            "source": "package-lock",
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


def plan_npm_graphs(graph: ProjectGraph, selector: str | None = None) -> list[NpmGraphPlan]:
    candidates = [
        component
        for component in graph.components
        if component.ecosystem == "node"
        and component.manager == "npm"
        and any(name in component.lockfiles for name in ("package-lock.json", "npm-shrinkwrap.json"))
    ]
    if selector is not None:
        candidates = [component for component in candidates if _matches(component, graph, selector)]
        if not candidates:
            return []
        if len(candidates) > 1:
            choices = ", ".join(component.key(graph.root) for component in candidates)
            raise NpmGraphError(f"Component selector '{selector}' is ambiguous for npm graph ingestion: {choices}")
    return [NpmGraphPlan(component.key(graph.root), component.path) for component in candidates]


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
            if not isinstance(name, str) or not isinstance(record, dict):
                continue
            version = record.get("version") if isinstance(record.get("version"), str) else None
            child_ref = _ref(parent_ref, name, version, ordinal)
            package = NpmLogicalPackage(
                component=component,
                ref=child_ref,
                name=name,
                version=version,
                parent_ref=parent_ref,
                depth=depth,
                direct=depth == 1,
                overridden=bool(record.get("overridden")),
                resolved=record.get("resolved") if isinstance(record.get("resolved"), str) else None,
            )
            packages.append(package)
            edges.append(NpmLogicalEdge(component, parent_ref, child_ref, name))
            visit(record.get("dependencies"), child_ref, depth + 1)

    visit(data.get("dependencies"), root_ref, 1)
    raw_problems = data.get("problems")
    problems = tuple(str(item) for item in raw_problems) if isinstance(raw_problems, list) else ()
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

    output = completed.stdout or ""
    if not output.strip():
        return NpmGraphResult(
            plan,
            [],
            [],
            completed.returncode,
            stderr=(completed.stderr or "npm ls produced no JSON output").strip(),
        )
    try:
        root_name, root_version, packages, edges, problems = parse_npm_ls(output, plan.component)
    except NpmGraphError as exc:
        return NpmGraphResult(plan, [], [], completed.returncode or 1, stderr=str(exc))
    return NpmGraphResult(
        plan=plan,
        packages=packages,
        edges=edges,
        returncode=completed.returncode,
        root_name=root_name,
        root_version=root_version,
        problems=problems,
        stderr=(completed.stderr or "").strip(),
    )
