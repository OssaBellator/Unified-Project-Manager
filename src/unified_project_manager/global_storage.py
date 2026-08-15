from __future__ import annotations

import os
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


def _run_path_query(
    manager: str,
    argv_tail: tuple[str, ...],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]],
    which: Callable[[str], str | None],
) -> tuple[Path | None, GlobalStorageSkip | None]:
    executable = which(manager)
    if executable is None:
        return None, GlobalStorageSkip(manager, f"{manager} executable is not available on PATH")
    argv = [executable, *argv_tail]
    try:
        completed = run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        return None, GlobalStorageSkip(manager, f"Could not query cache/store path: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return None, GlobalStorageSkip(manager, detail or f"path query exited with {completed.returncode}")
    value = next((line.strip() for line in (completed.stdout or "").splitlines() if line.strip()), "")
    if not value or value.lower() in {"undefined", "null", "off"}:
        return None, GlobalStorageSkip(manager, "native path query returned no usable cache/store path")
    return Path(value).expanduser(), None


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


def _manager_cache_paths(
    manager: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]],
    which: Callable[[str], str | None],
) -> tuple[list[tuple[str, Path]], GlobalStorageSkip | None]:
    if manager == "go":
        return _go_cache_paths(run=run, which=which)
    if manager == "npm":
        path, skip = _run_path_query("npm", ("get", "cache"), run=run, which=which)
        return ([] if path is None else [("package-cache", path)]), skip
    if manager == "pnpm":
        path, skip = _run_path_query("pnpm", ("store", "path"), run=run, which=which)
        return ([] if path is None else [("content-store", path)]), skip
    if manager == "uv":
        path, skip = _run_path_query("uv", ("cache", "dir"), run=run, which=which)
        return ([] if path is None else [("package-cache", path)]), skip
    if manager == "cargo":
        cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo"))).expanduser()
        return [
            ("registry-cache", cargo_home / "registry"),
            ("git-cache", cargo_home / "git"),
        ], None
    return [], GlobalStorageSkip(manager, "global cache storage probing is not configured for this manager yet")


def global_cache_storage(
    *,
    managers: tuple[str, ...] = ("go", "npm", "pnpm", "uv", "cargo"),
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[list[GlobalStorageEntry], list[GlobalStorageSkip]]:
    entries: list[GlobalStorageEntry] = []
    skips: list[GlobalStorageSkip] = []
    seen: set[tuple[int, int]] = set()

    for manager in dict.fromkeys(managers):
        paths, skip = _manager_cache_paths(manager, run=run, which=which)
        if skip is not None:
            skips.append(skip)
            continue
        for category, path in paths:
            if not path.is_dir() or path.is_symlink():
                entries.append(GlobalStorageEntry(manager, category, str(path), 0, 0))
                continue
            size, files = directory_size(path, seen=seen)
            entries.append(GlobalStorageEntry(manager, category, str(path.resolve()), size, files))

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
