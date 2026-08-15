from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Component, ProjectGraph


class NativeGraphError(ValueError):
    """Raised when an authoritative native dependency graph cannot be queried safely."""


@dataclass(frozen=True)
class NativeGraphPlan:
    component: str
    ecosystem: str
    manager: str
    cwd: Path
    selected_argv: tuple[str, ...]
    edges_argv: tuple[str, ...]

    def to_dict(self, root: Path) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": self.ecosystem,
            "manager": self.manager,
            "cwd": self.cwd.relative_to(root).as_posix() or ".",
            "selected_argv": list(self.selected_argv),
            "edges_argv": list(self.edges_argv),
        }


@dataclass(frozen=True)
class NativeGraphSkip:
    component: str
    ecosystem: str
    manager: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NativeModule:
    component: str
    name: str
    version: str | None
    main: bool = False
    replacement_name: str | None = None
    replacement_version: str | None = None
    replacement_dir: str | None = None
    indirect: bool = False
    directory: str | None = None
    go_mod: str | None = None
    go_version: str | None = None
    checksum: str | None = None
    go_mod_checksum: str | None = None
    origin: dict[str, Any] | None = None
    reuse: bool = False
    replacement_go_version: str | None = None
    replacement_checksum: str | None = None
    replacement_go_mod_checksum: str | None = None
    replacement_origin: dict[str, Any] | None = None

    @property
    def is_local_replacement(self) -> bool:
        return self.replacement_name is not None and self.replacement_version is None

    @property
    def effective_name(self) -> str:
        return self.replacement_name or self.name

    @property
    def effective_version(self) -> str | None:
        if self.replacement_name is not None:
            return self.replacement_version
        return self.version

    @property
    def effective_go_version(self) -> str | None:
        if self.replacement_name is not None and self.replacement_go_version:
            return self.replacement_go_version
        return self.go_version

    @property
    def effective_checksum(self) -> str | None:
        if self.replacement_name is not None:
            return self.replacement_checksum
        return self.checksum

    @property
    def effective_go_mod_checksum(self) -> str | None:
        if self.replacement_name is not None:
            return self.replacement_go_mod_checksum
        return self.go_mod_checksum

    @property
    def effective_origin(self) -> dict[str, Any] | None:
        if self.replacement_name is not None:
            return self.replacement_origin
        return self.origin

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "name": self.name,
            "version": self.version,
            "main": self.main,
            "indirect": self.indirect,
            "directory": self.directory,
            "go_mod": self.go_mod,
            "go_version": self.go_version,
            "checksum": self.checksum,
            "go_mod_checksum": self.go_mod_checksum,
            "origin": self.origin,
            "reuse": self.reuse,
            "replacement": (
                {
                    "name": self.replacement_name,
                    "version": self.replacement_version,
                    "dir": self.replacement_dir,
                    "go_version": self.replacement_go_version,
                    "checksum": self.replacement_checksum,
                    "go_mod_checksum": self.replacement_go_mod_checksum,
                    "origin": self.replacement_origin,
                    "local": self.is_local_replacement,
                }
                if self.replacement_name is not None
                else None
            ),
            "effective_name": self.effective_name,
            "effective_version": self.effective_version,
            "effective_go_version": self.effective_go_version,
            "effective_checksum": self.effective_checksum,
            "effective_go_mod_checksum": self.effective_go_mod_checksum,
            "effective_origin": self.effective_origin,
        }


@dataclass(frozen=True)
class NativeRequirementEdge:
    component: str
    source_name: str
    source_version: str | None
    target_name: str
    required_version: str | None
    selected_version: str | None
    source_selected: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NativeGraphResult:
    plan: NativeGraphPlan
    modules: list[NativeModule]
    edges: list[NativeRequirementEdge]
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
            "modules": [module.to_dict() for module in self.modules],
            "edges": [edge.to_dict() for edge in self.edges],
            "stderr": self.stderr,
        }


@dataclass(frozen=True)
class NativeWhyResult:
    component: str
    ecosystem: str
    module: str
    needed: bool
    path: tuple[str, ...]
    returncode: int
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "ecosystem": self.ecosystem,
            "module": self.module,
            "needed": self.needed,
            "path": list(self.path),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stderr": self.stderr,
        }


def _matches(component: Component, graph: ProjectGraph, selector: str) -> bool:
    return selector in {
        component.key(graph.root),
        component.relative_path(graph.root),
        component.ecosystem,
        component.metadata.get("name"),
    }


def _selected_components(graph: ProjectGraph, selector: str | None) -> list[Component]:
    if selector is None:
        return list(graph.components)
    matches = [component for component in graph.components if _matches(component, graph, selector)]
    if not matches:
        raise NativeGraphError(f"Unknown component '{selector}'.")
    if len(matches) > 1:
        choices = ", ".join(component.key(graph.root) for component in matches)
        raise NativeGraphError(f"Component selector '{selector}' is ambiguous: {choices}")
    return matches


def plan_native_graph(
    graph: ProjectGraph,
    selector: str | None = None,
) -> tuple[list[NativeGraphPlan], list[NativeGraphSkip]]:
    plans: list[NativeGraphPlan] = []
    skips: list[NativeGraphSkip] = []
    for component in _selected_components(graph, selector):
        key = component.key(graph.root)
        if component.ecosystem != "go" or component.manager != "go":
            skips.append(NativeGraphSkip(
                key,
                component.ecosystem,
                component.manager,
                "authoritative live transitive graph ingestion is not configured for this ecosystem yet",
            ))
            continue
        if component.metadata.get("parse_error"):
            skips.append(NativeGraphSkip(key, "go", "go", "go.mod is unreadable"))
            continue
        plans.append(NativeGraphPlan(
            component=key,
            ecosystem="go",
            manager="go",
            cwd=component.path,
            selected_argv=("go", "list", "-mod=readonly", "-m", "-json", "all"),
            edges_argv=("go", "mod", "graph"),
        ))
    return plans, skips


def _json_stream(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    index = 0
    values: list[dict[str, Any]] = []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise NativeGraphError(f"Could not parse native JSON module stream: {exc}") from exc
        if not isinstance(value, dict):
            raise NativeGraphError("Native module stream contained a non-object JSON value.")
        values.append(value)
    return values


def parse_go_selected_modules(text: str, component: str) -> list[NativeModule]:
    modules: list[NativeModule] = []
    for record in _json_stream(text):
        name = record.get("Path")
        if not isinstance(name, str) or not name:
            continue
        version = record.get("Version") if isinstance(record.get("Version"), str) else None
        replacement = record.get("Replace")
        replacement_name = replacement_version = replacement_dir = None
        replacement_go_version = replacement_checksum = replacement_go_mod_checksum = None
        replacement_origin = None
        if isinstance(replacement, dict):
            if isinstance(replacement.get("Path"), str):
                replacement_name = replacement["Path"]
            if isinstance(replacement.get("Version"), str):
                replacement_version = replacement["Version"]
            if isinstance(replacement.get("Dir"), str):
                replacement_dir = replacement["Dir"]
            if isinstance(replacement.get("GoVersion"), str):
                replacement_go_version = replacement["GoVersion"]
            if isinstance(replacement.get("Sum"), str):
                replacement_checksum = replacement["Sum"]
            if isinstance(replacement.get("GoModSum"), str):
                replacement_go_mod_checksum = replacement["GoModSum"]
            if isinstance(replacement.get("Origin"), dict):
                replacement_origin = dict(replacement["Origin"])
        modules.append(NativeModule(
            component=component,
            name=name,
            version=version,
            main=bool(record.get("Main")),
            replacement_name=replacement_name,
            replacement_version=replacement_version,
            replacement_dir=replacement_dir,
            indirect=bool(record.get("Indirect")),
            directory=record.get("Dir") if isinstance(record.get("Dir"), str) else None,
            go_mod=record.get("GoMod") if isinstance(record.get("GoMod"), str) else None,
            go_version=record.get("GoVersion") if isinstance(record.get("GoVersion"), str) else None,
            checksum=record.get("Sum") if isinstance(record.get("Sum"), str) else None,
            go_mod_checksum=record.get("GoModSum") if isinstance(record.get("GoModSum"), str) else None,
            origin=dict(record["Origin"]) if isinstance(record.get("Origin"), dict) else None,
            reuse=bool(record.get("Reuse")),
            replacement_go_version=replacement_go_version,
            replacement_checksum=replacement_checksum,
            replacement_go_mod_checksum=replacement_go_mod_checksum,
            replacement_origin=replacement_origin,
        ))
    return sorted(modules, key=lambda item: (not item.main, item.name, item.version or ""))


def _module_vertex(value: str) -> tuple[str, str | None]:
    if "@" not in value:
        return value, None
    name, version = value.rsplit("@", 1)
    return name, version or None


def parse_go_requirement_edges(
    text: str,
    component: str,
    modules: list[NativeModule],
) -> list[NativeRequirementEdge]:
    selected = {module.name: module.version for module in modules}
    main_names = {module.name for module in modules if module.main}
    edges: list[NativeRequirementEdge] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2:
            raise NativeGraphError(f"Could not parse go mod graph line {number}: {raw!r}")
        source_name, source_version = _module_vertex(fields[0])
        target_name, required_version = _module_vertex(fields[1])
        source_selected = source_name in main_names or selected.get(source_name) == source_version
        edges.append(NativeRequirementEdge(
            component=component,
            source_name=source_name,
            source_version=source_version,
            target_name=target_name,
            required_version=required_version,
            selected_version=selected.get(target_name),
            source_selected=source_selected,
        ))
    return sorted(edges, key=lambda item: (
        item.source_name,
        item.source_version or "",
        item.target_name,
        item.required_version or "",
    ))


def execute_native_graph(
    plan: NativeGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> NativeGraphResult:
    executable = which(plan.selected_argv[0])
    if executable is None:
        return NativeGraphResult(plan, [], [], 127, stderr="Executable 'go' is not available on PATH.")

    selected_argv = [executable, *plan.selected_argv[1:]]
    try:
        selected_result = run(selected_argv, cwd=plan.cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return NativeGraphResult(plan, [], [], 127, stderr=str(exc))
    if selected_result.returncode != 0:
        return NativeGraphResult(
            plan,
            [],
            [],
            selected_result.returncode,
            stderr=(selected_result.stderr or selected_result.stdout or "").strip(),
        )
    try:
        modules = parse_go_selected_modules(selected_result.stdout or "", plan.component)
    except NativeGraphError as exc:
        return NativeGraphResult(plan, [], [], 1, stderr=str(exc))

    edges_argv = [executable, *plan.edges_argv[1:]]
    try:
        edge_result = run(edges_argv, cwd=plan.cwd, text=True, capture_output=True, check=False)
    except OSError as exc:
        return NativeGraphResult(plan, modules, [], 127, stderr=str(exc))
    if edge_result.returncode != 0:
        return NativeGraphResult(
            plan,
            modules,
            [],
            edge_result.returncode,
            stderr=(edge_result.stderr or edge_result.stdout or "").strip(),
        )
    try:
        edges = parse_go_requirement_edges(edge_result.stdout or "", plan.component, modules)
    except NativeGraphError as exc:
        return NativeGraphResult(plan, modules, [], 1, stderr=str(exc))
    return NativeGraphResult(plan, modules, edges, 0)


def _parse_go_why(text: str) -> tuple[bool, tuple[str, ...]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    if not lines or (len(lines) == 1 and lines[0].startswith("(")):
        return False, ()
    return True, tuple(lines)


def query_native_why(
    graph: ProjectGraph,
    module: str,
    selector: str | None = None,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[list[NativeWhyResult], list[NativeGraphSkip]]:
    results: list[NativeWhyResult] = []
    skips: list[NativeGraphSkip] = []
    components = _selected_components(graph, selector)
    for component in components:
        key = component.key(graph.root)
        if component.ecosystem != "go" or component.manager != "go":
            skips.append(NativeGraphSkip(
                key,
                component.ecosystem,
                component.manager,
                "authoritative native why queries are not configured for this ecosystem yet",
            ))
            continue
        executable = which("go")
        if executable is None:
            results.append(NativeWhyResult(key, "go", module, False, (), 127, "Executable 'go' is not available on PATH."))
            continue
        argv = [executable, "mod", "why", "-m", module]
        try:
            completed = run(argv, cwd=component.path, text=True, capture_output=True, check=False)
        except OSError as exc:
            results.append(NativeWhyResult(key, "go", module, False, (), 127, str(exc)))
            continue
        if completed.returncode != 0:
            results.append(NativeWhyResult(
                key,
                "go",
                module,
                False,
                (),
                completed.returncode,
                (completed.stderr or completed.stdout or "").strip(),
            ))
            continue
        needed, path = _parse_go_why(completed.stdout or "")
        results.append(NativeWhyResult(key, "go", module, needed, path, 0, (completed.stderr or "").strip()))
    return results, skips


def selected_inventory(results: list[NativeGraphResult]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for result in results:
        if not result.succeeded:
            continue
        for module in result.modules:
            if module.main:
                continue
            inventory.append(module.to_dict())
    return sorted(inventory, key=lambda item: (
        item["name"],
        item.get("version") or "",
        item["component"],
    ))
