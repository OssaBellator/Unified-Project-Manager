from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .python_lock_graph import PythonLockGraphResult
from .python_lock_provider import PYTHON_LOCK_SCOPE, python_lock_provider_name
from .python_lock_reachability import (
    PythonLockAmbiguity,
    PythonLockReachablePackage,
    analyze_python_lock_reachability,
)


@dataclass(frozen=True)
class PythonLockProviderQueryResult:
    """One certainty-aware Poetry/PDM dependency query result.

    Project `why`, project `impact`, fleet impact, and advisory correlation use
    this same object so resolved, conditional, possible, and ambiguity evidence
    cannot drift between command surfaces.
    """

    provider: str
    scope: str
    component: str
    manager: str
    query: str
    packages: tuple[PythonLockReachablePackage, ...]
    possible_packages: tuple[PythonLockReachablePackage, ...]
    ambiguities: tuple[PythonLockAmbiguity, ...]
    search_truncated: bool = False

    @property
    def matched(self) -> bool:
        return bool(self.packages or self.possible_packages or self.ambiguities)

    @property
    def unconditional_matches(self) -> int:
        return sum(package.unconditional for package in self.packages)

    @property
    def conditional_matches(self) -> int:
        return sum(not package.unconditional for package in self.packages)

    @property
    def uncertain(self) -> bool:
        return bool(
            self.ambiguities
            or self.possible_packages
            or self.conditional_matches
            or self.search_truncated
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "scope": self.scope,
            "component": self.component,
            "manager": self.manager,
            "query": self.query,
            "matched": self.matched,
            "uncertain": self.uncertain,
            "search_truncated": self.search_truncated,
            # Keep the existing summary keys stable for callers that compare the
            # command-neutral contract exactly. Possible matches are represented
            # explicitly in `possible_packages` rather than being relabeled as
            # conditional resolved packages.
            "summary": {
                "packages": len(self.packages),
                "unconditional_matches": self.unconditional_matches,
                "conditional_matches": self.conditional_matches,
                "ambiguities": len(self.ambiguities),
            },
            "packages": [package.to_dict() for package in self.packages],
            "possible_packages": [package.to_dict() for package in self.possible_packages],
            "ambiguities": [ambiguity.to_dict() for ambiguity in self.ambiguities],
            "interpretation": "dependency reachability only; not source/API/runtime reachability or exploitability",
        }


def query_python_lock_result(
    result: PythonLockGraphResult,
    package_name: str,
) -> PythonLockProviderQueryResult:
    report = analyze_python_lock_reachability(result, package_name)
    return PythonLockProviderQueryResult(
        provider=python_lock_provider_name(result.plan.manager),
        scope=PYTHON_LOCK_SCOPE,
        component=result.plan.component,
        manager=result.plan.manager,
        query=package_name,
        packages=report.packages,
        possible_packages=report.possible_packages,
        ambiguities=report.ambiguities,
        search_truncated=report.search_truncated,
    )


def query_python_lock_results(
    results: Iterable[PythonLockGraphResult],
    package_name: str,
) -> list[PythonLockProviderQueryResult]:
    queried = [query_python_lock_result(result, package_name) for result in results]
    return sorted(
        queried,
        key=lambda item: (item.component, item.provider, item.query.lower()),
    )
