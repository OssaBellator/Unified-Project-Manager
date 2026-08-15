from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .go_symbol_correlation import GovulncheckSymbolCorrelation, correlate_govulncheck_symbols
from .go_symbol_execution import GovulncheckSymbolExecution


@dataclass(frozen=True)
class GoSymbolProjectReport:
    project: str
    component: str
    execution: GovulncheckSymbolExecution
    correlation: GovulncheckSymbolCorrelation | None

    @property
    def execution_succeeded(self) -> bool:
        return self.execution.succeeded

    @property
    def correlated_matches(self) -> int:
        return len(self.correlation.matches) if self.correlation is not None else 0

    @property
    def unmatched_symbol_findings(self) -> int:
        return len(self.correlation.unmatched) if self.correlation is not None else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "component": self.component,
            "execution_succeeded": self.execution_succeeded,
            "execution": self.execution.to_dict(),
            "correlation": self.correlation.to_dict() if self.correlation is not None else None,
            "correlated_matches": self.correlated_matches,
            "unmatched_symbol_findings": self.unmatched_symbol_findings,
            "provider": "govulncheck",
            "scope": "vulnerable-symbol-call-graph",
            "public": False,
            "persisted": False,
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
        }


@dataclass(frozen=True)
class GoSymbolFleetReport:
    projects: tuple[GoSymbolProjectReport, ...]

    @property
    def summary(self) -> dict[str, int]:
        return {
            "projects": len(self.projects),
            "execution_succeeded": sum(1 for item in self.projects if item.execution_succeeded),
            "execution_failed_or_blocked": sum(1 for item in self.projects if not item.execution_succeeded),
            "symbol_findings": sum(item.execution.symbol_findings for item in self.projects),
            "correlated_matches": sum(item.correlated_matches for item in self.projects),
            "unmatched_symbol_findings": sum(item.unmatched_symbol_findings for item in self.projects),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "projects": [item.to_dict() for item in self.projects],
            "provider": "govulncheck",
            "scope": "vulnerable-symbol-call-graph",
            "public": False,
            "persisted": False,
            "interpretation": (
                "pre-public static vulnerable-symbol reporting only; execution and correlation remain "
                "separate from runtime/data-flow reachability and exploitability"
            ),
        }


def build_go_symbol_project_report(
    project: str | Path,
    *,
    component: str,
    execution: GovulncheckSymbolExecution,
    dependency_impacts: list[dict[str, Any]],
) -> GoSymbolProjectReport:
    """Build one pre-public project symbol report without performing execution.

    Correlation is attempted only for a valid completed symbol execution. A
    blocked/failed/invalid execution remains visible as execution evidence and
    cannot manufacture empty or negative symbol-correlation evidence.
    """

    project_name = str(Path(project).expanduser().resolve())
    correlation = None
    if execution.succeeded and execution.report is not None:
        correlation = correlate_govulncheck_symbols(
            execution.report,
            dependency_impacts,
            component=component,
        )
    return GoSymbolProjectReport(project_name, component, execution, correlation)


def build_go_symbol_fleet_report(
    projects: Iterable[GoSymbolProjectReport],
) -> GoSymbolFleetReport:
    """Aggregate already-built project reports without executing or correlating again."""

    ordered = tuple(sorted(
        projects,
        key=lambda item: (item.project, item.component),
    ))
    return GoSymbolFleetReport(ordered)
