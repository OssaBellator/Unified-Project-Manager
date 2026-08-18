from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .adapters import DEFAULT_ADAPTERS, Adapter
from .adapters.dotnet import dotnet_solution_files
from .models import ProjectGraph, Workspace

IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "target",
    "dist", "build", "__pycache__", ".mypy_cache", ".ruff_cache", ".tox",
}


def discover(root: str | Path, adapters: Iterable[Adapter] = DEFAULT_ADAPTERS) -> ProjectGraph:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    adapters = tuple(adapters)
    components = []
    workspaces = []
    for current, directories, _files in os.walk(root_path):
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRECTORIES and not name.startswith(".upm")
        )
        directory = Path(current)

        solution_files = dotnet_solution_files(directory)
        if solution_files:
            workspaces.append(Workspace(
                ecosystem="dotnet",
                path=directory,
                manager="nuget",
                manifests=list(solution_files),
                metadata={"kind": "solution", "ambiguous": len(solution_files) > 1},
            ))

        if (directory / "go.work").is_file():
            workspaces.append(Workspace(
                ecosystem="go",
                path=directory,
                manager="go",
                manifests=["go.work"],
                lockfiles=["go.work.sum"] if (directory / "go.work.sum").is_file() else [],
            ))

        for adapter in adapters:
            if adapter.detect(directory):
                components.append(adapter.inspect(directory))

    components.sort(key=lambda item: (item.path.relative_to(root_path).as_posix(), item.ecosystem))
    workspaces.sort(key=lambda item: (item.path.relative_to(root_path).as_posix(), item.ecosystem))
    return ProjectGraph(root=root_path, components=components, workspaces=workspaces)
