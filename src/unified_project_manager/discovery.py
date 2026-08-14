from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .adapters import DEFAULT_ADAPTERS, Adapter
from .models import ProjectGraph

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
    for current, directories, _files in os.walk(root_path):
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRECTORIES and not name.startswith(".upm")
        )
        directory = Path(current)
        for adapter in adapters:
            if adapter.detect(directory):
                components.append(adapter.inspect(directory))

    components.sort(key=lambda item: (item.path.relative_to(root_path).as_posix(), item.ecosystem))
    return ProjectGraph(root=root_path, components=components)
