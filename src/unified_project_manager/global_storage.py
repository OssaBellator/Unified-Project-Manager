from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .storage import directory_size


@dataclass(frozen=True)
class GlobalStorageSkip:
    manager: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class GlobalStorageEntry:
    manager: str
    category: str
    path: str
    bytes: int
    files: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _go_cache_paths(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[list[tuple[str, Path]], GlobalStorageSkip | None]:
    executable = which("go")
    if executable is None:
        return [], GlobalStorageSkip("go", "Go executable is not available on PATH")
    argv = [executable, "env", "GOMODCACHE", "GOCACHE"]
    try:
        completed = run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        return [], GlobalStorageSkip("go", f"Could not query Go cache paths: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return [], GlobalStorageSkip("go", detail or f"go env exited with {completed.returncode}")
    values = [line.strip() for line in (completed.stdout or "").splitlines()]
    if len(values) < 2:
        return [], GlobalStorageSkip("go", "go env did not return both GOMODCACHE and GOCACHE")
    result = []
    for category, value in (("module-cache", values[0]), ("build-cache", values[1])):
        if not value or value.lower() == "off":
            continue
        result.append((category, Path(value).expanduser()))
    return result, None


def global_cache_storage(
    *,
    managers: tuple[str, ...] = ("go",),
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[list[GlobalStorageEntry], list[GlobalStorageSkip]]:
    entries: list[GlobalStorageEntry] = []
    skips: list[GlobalStorageSkip] = []
    seen: set[tuple[int, int]] = set()

    for manager in managers:
        if manager != "go":
            skips.append(GlobalStorageSkip(manager, "global cache storage probing is not configured for this manager yet"))
            continue
        paths, skip = _go_cache_paths(run=run, which=which)
        if skip is not None:
            skips.append(skip)
            continue
        for category, path in paths:
            if not path.is_dir() or path.is_symlink():
                entries.append(GlobalStorageEntry("go", category, str(path), 0, 0))
                continue
            size, files = directory_size(path, seen=seen)
            entries.append(GlobalStorageEntry("go", category, str(path.resolve()), size, files))

    return sorted(entries, key=lambda item: (item.manager, item.category, item.path)), skips


def global_storage_summary(entries: list[GlobalStorageEntry]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    managers: dict[str, int] = {}
    total = 0
    for entry in entries:
        total += entry.bytes
        categories[entry.category] = categories.get(entry.category, 0) + entry.bytes
        managers[entry.manager] = managers.get(entry.manager, 0) + entry.bytes
    return {
        "bytes": total,
        "categories": dict(sorted(categories.items())),
        "managers": dict(sorted(managers.items())),
    }
