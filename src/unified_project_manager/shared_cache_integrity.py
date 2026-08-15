from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SharedCachePlan:
    manager: str
    argv: tuple[str, ...]
    mutates: bool
    effect: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SharedCacheSkip:
    manager: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SharedCacheResult:
    plan: SharedCachePlan
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


def plan_shared_cache_checks(
    managers: tuple[str, ...] = ("pnpm",),
) -> tuple[list[SharedCachePlan], list[SharedCacheSkip]]:
    plans: list[SharedCachePlan] = []
    skips: list[SharedCacheSkip] = []
    for manager in dict.fromkeys(managers):
        if manager == "pnpm":
            plans.append(SharedCachePlan(
                "pnpm",
                ("pnpm", "store", "status"),
                False,
                "checks the pnpm content-addressable store for modified packages",
            ))
        else:
            skips.append(SharedCacheSkip(
                manager,
                "no documented non-mutating shared-cache integrity check is configured for this manager",
            ))
    return plans, skips


def plan_shared_cache_maintenance(
    managers: tuple[str, ...] = ("npm",),
) -> tuple[list[SharedCachePlan], list[SharedCacheSkip]]:
    plans: list[SharedCachePlan] = []
    skips: list[SharedCacheSkip] = []
    for manager in dict.fromkeys(managers):
        if manager == "npm":
            plans.append(SharedCachePlan(
                "npm",
                ("npm", "cache", "verify"),
                True,
                "verifies npm cache integrity and garbage-collects unneeded cache data",
            ))
        else:
            skips.append(SharedCacheSkip(
                manager,
                "no explicit shared-cache maintenance verifier is configured for this manager",
            ))
    return plans, skips


def execute_shared_cache_plan(
    plan: SharedCachePlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> SharedCacheResult:
    executable = which(plan.argv[0])
    if executable is None:
        return SharedCacheResult(plan, 127, stderr=f"Executable '{plan.argv[0]}' is not available on PATH.")
    argv = [executable, *plan.argv[1:]]
    try:
        completed = run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        return SharedCacheResult(plan, 127, stderr=str(exc))
    return SharedCacheResult(plan, completed.returncode, completed.stdout or "", completed.stderr or "")
