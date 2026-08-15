from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

CacheAction = Literal["prune", "clean"]


class CacheMaintenanceError(ValueError):
    """Raised when cache maintenance cannot be planned safely."""


@dataclass(frozen=True)
class CacheMaintenancePlan:
    manager: str
    action: CacheAction
    scope: str
    argv: tuple[str, ...]
    effect: str
    destructive: bool
    redownload_or_rebuild_possible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CacheMaintenanceResult:
    plan: CacheMaintenancePlan
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "returncode": self.returncode,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def plan_cache_prune(managers: tuple[str, ...] = ("pnpm", "uv")) -> list[CacheMaintenancePlan]:
    plans: list[CacheMaintenancePlan] = []
    for manager in dict.fromkeys(managers):
        if manager == "pnpm":
            plans.append(CacheMaintenancePlan(
                manager="pnpm",
                action="prune",
                scope="content-addressable-store",
                argv=("pnpm", "store", "prune"),
                effect="removes packages pnpm considers unreferenced from the shared store",
                destructive=True,
                redownload_or_rebuild_possible=True,
            ))
        elif manager == "uv":
            plans.append(CacheMaintenancePlan(
                manager="uv",
                action="prune",
                scope="package-cache",
                argv=("uv", "cache", "prune"),
                effect="removes unused uv cache entries and centralized project environments",
                destructive=True,
                redownload_or_rebuild_possible=True,
            ))
        else:
            raise CacheMaintenanceError(f"No authoritative prune operation is configured for manager '{manager}'.")
    return plans


def plan_cache_clean(manager: str, *, go_category: str | None = None) -> CacheMaintenancePlan:
    if manager == "npm":
        if go_category is not None:
            raise CacheMaintenanceError("--category is only valid when cleaning Go caches.")
        return CacheMaintenancePlan(
            manager="npm",
            action="clean",
            scope="package-cache",
            argv=("npm", "cache", "clean", "--force"),
            effect="removes all entries from npm's configured package cache",
            destructive=True,
            redownload_or_rebuild_possible=True,
        )
    if manager == "go":
        if go_category == "build":
            return CacheMaintenancePlan(
                manager="go",
                action="clean",
                scope="build-cache",
                argv=("go", "clean", "-cache"),
                effect="removes the entire Go build cache",
                destructive=True,
                redownload_or_rebuild_possible=True,
            )
        if go_category == "modules":
            return CacheMaintenancePlan(
                manager="go",
                action="clean",
                scope="module-cache",
                argv=("go", "clean", "-modcache"),
                effect="removes the entire downloaded Go module cache",
                destructive=True,
                redownload_or_rebuild_possible=True,
            )
        raise CacheMaintenanceError("Go cache clean requires --category build or --category modules.")
    raise CacheMaintenanceError(f"No authoritative full-cache clean operation is configured for manager '{manager}'.")


def execute_cache_maintenance(
    plan: CacheMaintenancePlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> CacheMaintenanceResult:
    executable = which(plan.argv[0])
    if executable is None:
        return CacheMaintenanceResult(plan, 127, stderr=f"Executable '{plan.argv[0]}' is not available on PATH.")
    try:
        completed = run(
            [executable, *plan.argv[1:]],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return CacheMaintenanceResult(plan, 127, stderr=str(exc))
    return CacheMaintenanceResult(plan, completed.returncode, completed.stdout or "", completed.stderr or "")
