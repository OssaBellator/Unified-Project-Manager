from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .go_symbol_preflight import GovulncheckSymbolPreflight, preflight_govulncheck_symbol
from .go_symbol_reachability import (
    GoSymbolReachabilityError,
    GovulncheckReport,
    GovulncheckSymbolPlan,
    parse_govulncheck_symbol_stream,
)


@dataclass(frozen=True)
class GovulncheckSymbolExecution:
    plan: GovulncheckSymbolPlan
    preflight: GovulncheckSymbolPreflight
    returncode: int | None
    report: GovulncheckReport | None
    stderr: str
    error: str | None
    launched: bool

    @property
    def succeeded(self) -> bool:
        return self.launched and self.returncode == 0 and self.report is not None and self.error is None

    @property
    def symbol_findings(self) -> int:
        return len(self.report.symbol_findings) if self.report is not None else 0

    @property
    def vulnerability_records(self) -> int:
        return len(self.report.aliases) if self.report is not None else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "launched": self.launched,
            "returncode": self.returncode,
            "stderr": self.stderr,
            "error": self.error,
            "preflight": self.preflight.to_dict(),
            "report": self.report.to_dict() if self.report is not None else None,
            "symbol_findings": self.symbol_findings,
            "vulnerability_records": self.vulnerability_records,
            "provider": "govulncheck",
            "scope": "vulnerable-symbol-call-graph",
            "public": False,
            "network": "disabled-by-local-db-and-go-environment",
            "project_mutation": "none-planned; real-runtime verification still required",
            "non_project_cache_tool_mutation": "possible",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "persisted": False,
        }


def _blocked_execution(
    plan: GovulncheckSymbolPlan,
    preflight: GovulncheckSymbolPreflight,
    reason: str | None = None,
) -> GovulncheckSymbolExecution:
    detail = reason or "; ".join(preflight.reasons) or "govulncheck symbol preflight is not ready"
    return GovulncheckSymbolExecution(
        plan=plan,
        preflight=preflight,
        returncode=None,
        report=None,
        stderr="",
        error=f"govulncheck symbol execution blocked by preflight: {detail}",
        launched=False,
    )


def _preflight_matches_plan(
    plan: GovulncheckSymbolPlan,
    preflight: GovulncheckSymbolPreflight,
) -> str | None:
    expected_project = str(Path(plan.cwd).expanduser().resolve())
    expected_database = str(Path(plan.database).expanduser().resolve())
    if preflight.project != expected_project:
        return (
            "preflight project does not match execution plan: "
            f"expected {expected_project!r}, observed {preflight.project!r}"
        )
    if preflight.database != expected_database:
        return (
            "preflight vulnerability database does not match execution plan: "
            f"expected {expected_database!r}, observed {preflight.database!r}"
        )
    return None


def execute_govulncheck_symbol(
    plan: GovulncheckSymbolPlan,
    *,
    preflight: GovulncheckSymbolPreflight | None = None,
    preflight_fn: Callable[..., GovulncheckSymbolPreflight] = preflight_govulncheck_symbol,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> GovulncheckSymbolExecution:
    """Execute a pre-public govulncheck source/symbol plan after strict preflight.

    Govulncheck JSON output intentionally exits 0 even when vulnerabilities are
    detected. Therefore return code 0 means the scan command completed; symbol
    vulnerability presence is derived only from the validated streaming report.
    Any nonzero exit is an execution failure and is never parsed as valid symbol
    evidence.
    """

    checked = preflight if preflight is not None else preflight_fn(plan)
    mismatch = _preflight_matches_plan(plan, checked)
    if mismatch is not None:
        return _blocked_execution(plan, checked, mismatch)
    if not checked.ready:
        return _blocked_execution(plan, checked)
    if not checked.govulncheck_executable:
        return _blocked_execution(
            plan,
            checked,
            "preflight was marked ready without a resolved govulncheck executable",
        )

    argv = [checked.govulncheck_executable, *plan.argv[1:]]
    environment = dict(os.environ)
    environment.update(plan.environment)
    try:
        completed = run(
            argv,
            cwd=plan.cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return GovulncheckSymbolExecution(
            plan=plan,
            preflight=checked,
            returncode=127,
            report=None,
            stderr="",
            error=str(exc),
            launched=True,
        )

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or (completed.stdout or "").strip()
        error = f"govulncheck symbol execution failed with exit code {completed.returncode}"
        if detail:
            error += f": {detail}"
        return GovulncheckSymbolExecution(
            plan=plan,
            preflight=checked,
            returncode=completed.returncode,
            report=None,
            stderr=stderr,
            error=error,
            launched=True,
        )

    try:
        report = parse_govulncheck_symbol_stream(completed.stdout or "")
    except GoSymbolReachabilityError as exc:
        return GovulncheckSymbolExecution(
            plan=plan,
            preflight=checked,
            returncode=completed.returncode,
            report=None,
            stderr=stderr,
            error=f"govulncheck JSON evidence is invalid: {exc}",
            launched=True,
        )

    if report.config.database != plan.database_uri:
        return GovulncheckSymbolExecution(
            plan=plan,
            preflight=checked,
            returncode=completed.returncode,
            report=None,
            stderr=stderr,
            error=(
                "govulncheck reported a vulnerability database different from the planned local database: "
                f"expected {plan.database_uri!r}, observed {report.config.database!r}"
            ),
            launched=True,
        )

    return GovulncheckSymbolExecution(
        plan=plan,
        preflight=checked,
        returncode=completed.returncode,
        report=report,
        stderr=stderr,
        error=None,
        launched=True,
    )
