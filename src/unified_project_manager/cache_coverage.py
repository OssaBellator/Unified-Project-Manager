from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import ProjectGraph


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
