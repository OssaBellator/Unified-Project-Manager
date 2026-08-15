from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable

from .go_workspace import plan_workspace_inspection
from .models import ProjectGraph
from .native_graph import (
    NativeGraphPlan,
    NativeGraphResult,
    NativeGraphError,
    parse_go_requirement_edges,
    parse_go_selected_modules,
)


def plan_workspace_graph(graph: ProjectGraph, selector: str | None = None) -> NativeGraphPlan:
    inspection = plan_workspace_inspection(graph, selector)
    return NativeGraphPlan(
        component=inspection.workspace,
        ecosystem="go",
        manager="go",
        cwd=inspection.cwd,
        selected_argv=("go", "list", "-mod=readonly", "-m", "-json", "all"),
        edges_argv=("go", "mod", "graph"),
    )


def _workspace_environment(plan: NativeGraphPlan) -> dict[str, str]:
    environment = dict(os.environ)
    environment["GOWORK"] = str(plan.cwd / "go.work")
    current_flags = environment.get("GOFLAGS", "").strip()
    environment["GOFLAGS"] = f"{current_flags} -mod=readonly".strip()
    return environment


def execute_workspace_graph(
    plan: NativeGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> NativeGraphResult:
    executable = which("go")
    if executable is None:
        return NativeGraphResult(plan, [], [], 127, stderr="Executable 'go' is not available on PATH.")

    environment = _workspace_environment(plan)
    try:
        selected_result = run(
            [executable, *plan.selected_argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
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

    try:
        graph_result = run(
            [executable, *plan.edges_argv[1:]],
            cwd=plan.cwd,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
    except OSError as exc:
        return NativeGraphResult(plan, modules, [], 127, stderr=str(exc))
    if graph_result.returncode != 0:
        return NativeGraphResult(
            plan,
            modules,
            [],
            graph_result.returncode,
            stderr=(graph_result.stderr or graph_result.stdout or "").strip(),
        )
    try:
        edges = parse_go_requirement_edges(graph_result.stdout or "", plan.component, modules)
    except NativeGraphError as exc:
        return NativeGraphResult(plan, modules, [], 1, stderr=str(exc))
    return NativeGraphResult(plan, modules, edges, 0)
