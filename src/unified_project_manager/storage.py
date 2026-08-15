from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import ProjectGraph

ARTIFACT_DIRECTORIES = {
    "node": (("node_modules", "packages"),),
    "python": ((".venv", "environment"), ("__pypackages__", "environment")),
    "rust": (("target", "build"),),
}


def directory_size(path: str | Path) -> tuple[int, int]:
    root = Path(path)
    if not root.is_dir() or root.is_symlink():
        return 0, 0
    total = 0
    files = 0
    seen: set[tuple[int, int]] = set()
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    identity = (stat.st_dev, stat.st_ino)
                    if stat.st_ino and identity in seen:
                        continue
                    if stat.st_ino:
                        seen.add(identity)
                    total += stat.st_size
                    files += 1
        except OSError:
            continue
    return total, files


def project_storage(graph: ProjectGraph) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for component in graph.components:
        for relative, category in ARTIFACT_DIRECTORIES.get(component.ecosystem, ()):
            target = component.path / relative
            if not target.is_dir() or target.is_symlink():
                continue
            size, files = directory_size(target)
            entries.append({
                "component": component.key(graph.root),
                "ecosystem": component.ecosystem,
                "manager": component.manager,
                "category": category,
                "path": target.relative_to(graph.root).as_posix(),
                "bytes": size,
                "files": files,
            })
    return sorted(entries, key=lambda item: (item["component"], item["category"], item["path"]))


def storage_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    total = 0
    for entry in entries:
        size = int(entry.get("bytes", 0))
        total += size
        category = str(entry.get("category", "other"))
        categories[category] = categories.get(category, 0) + size
    return {"bytes": total, "categories": dict(sorted(categories.items()))}
