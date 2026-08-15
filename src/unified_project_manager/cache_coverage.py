from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ProjectGraph
from .storage import directory_size


@dataclass(frozen=True)
class GoCacheAttributionSummary:
    total_bytes: int
    attributed_bytes: int
    unattributed_bytes: int
    coverage_complete: bool
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "attributed_bytes": self.attributed_bytes,
            "unattributed_bytes": self.unattributed_bytes,
            "coverage_ratio": (self.attributed_bytes / self.total_bytes) if self.total_bytes else None,
            "coverage_complete": self.coverage_complete,
            "limitations": list(self.limitations),
            "unattributed_means_unused": False,
            "reclaimable_bytes": None,
            "reclaimable": False,
        }


def summarize_go_cache_attribution(
    cache_root: str | Path,
    groups: list[object],
    *,
    provider_failures: list[str] | tuple[str, ...] = (),
    unregistered_projects_possible: bool = True,
) -> GoCacheAttributionSummary:
    """Summarize measured Go cache attribution without inferring reclaimability."""

    root = Path(cache_root).expanduser().resolve()
    total_bytes, _ = directory_size(root)
    attributed_bytes = 0
    seen: set[tuple[int, int]] = set()
    limitations = [str(item) for item in provider_failures]

    for group in groups:
        raw_path = getattr(group, "path", None)
        if not isinstance(raw_path, str) or not raw_path:
            limitations.append("cache attribution group did not expose a physical path")
            continue
        path = Path(raw_path).expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError:
            limitations.append(f"attributed cache path is outside measured GOMODCACHE: {path}")
            continue
        if path.is_symlink():
            limitations.append(f"attributed cache path is a symlink and was not measured: {path}")
            continue
        if path.is_dir():
            size, _ = directory_size(path, seen=seen)
        elif path.is_file():
            try:
                stat = path.stat()
            except OSError:
                limitations.append(f"could not measure attributed cache path: {path}")
                continue
            identity = (stat.st_dev, stat.st_ino)
            if stat.st_ino and identity in seen:
                size = 0
            else:
                if stat.st_ino:
                    seen.add(identity)
                size = stat.st_size
        else:
            limitations.append(f"attributed cache path is unavailable: {path}")
            continue
        attributed_bytes += size

    if unregistered_projects_possible:
        limitations.append("other unregistered projects may use the measured Go cache")
    if attributed_bytes > total_bytes:
        limitations.append("attributed bytes exceed the measured Go cache total")

    return GoCacheAttributionSummary(
        total_bytes=total_bytes,
        attributed_bytes=attributed_bytes,
        unattributed_bytes=max(total_bytes - attributed_bytes, 0),
        coverage_complete=not limitations,
        limitations=tuple(limitations),
    )


@dataclass(frozen=True)
class CacheIntegrityCoverage:
    component: str
    manager: str | None
    supported: bool
    mode: str | None
    mutates_cache: bool | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cache_integrity_coverage(graph: ProjectGraph) -> list[CacheIntegrityCoverage]:
    result: list[CacheIntegrityCoverage] = []
    for component in graph.components:
        key = component.key(graph.root)
        manager = component.manager
        if manager == "pnpm":
            result.append(CacheIntegrityCoverage(
                key,
                manager,
                True,
                "shared-store-status",
                False,
                "pnpm store status checks the shared content-addressable store for modified packages",
            ))
        elif manager == "go":
            result.append(CacheIntegrityCoverage(
                key,
                manager,
                True,
                "isolated-project-cache-verify",
                True,
                "Go module-cache verification isolates project go.mod/go.sum but may populate shared cache metadata",
            ))
        elif manager == "npm":
            result.append(CacheIntegrityCoverage(
                key,
                manager,
                True,
                "shared-cache-maintenance-verify",
                True,
                "npm cache verify checks integrity and also garbage-collects unneeded cache data",
            ))
        else:
            result.append(CacheIntegrityCoverage(
                key,
                manager,
                False,
                None,
                None,
                "no authoritative cache-integrity mechanism is configured for this manager",
            ))
    return result
