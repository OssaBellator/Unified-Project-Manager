from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from .go_offline import offline_go_run
from .models import ProjectGraph
from .native_graph import (
    NativeGraphPlan,
    NativeGraphResult,
    NativeGraphSkip,
    NativeWhyResult,
    execute_native_graph,
    query_native_why,
)


def _offline_runner(
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def wrapped(argv: list[str], **kwargs):
        return offline_go_run(argv, run=run, **kwargs)
    return wrapped


def execute_native_graph_offline(
    plan: NativeGraphPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> NativeGraphResult:
    """Execute a component-scoped Go graph with proxy and ambient workspace use disabled."""
    return execute_native_graph(plan, run=_offline_runner(run), which=which)


def query_native_why_offline(
    graph: ProjectGraph,
    module: str,
    selector: str | None = None,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[list[NativeWhyResult], list[NativeGraphSkip]]:
    """Run component-scoped `go mod why -m` with GOPROXY=off and GOWORK=off."""
    return query_native_why(
        graph,
        module,
        selector=selector,
        run=_offline_runner(run),
        which=which,
    )
