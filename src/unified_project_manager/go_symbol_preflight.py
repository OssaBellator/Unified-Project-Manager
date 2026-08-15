from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .go_symbol_reachability import GovulncheckSymbolPlan


@dataclass(frozen=True)
class GovulncheckSymbolPreflight:
    ready: bool
    project: str
    go_executable: str | None
    govulncheck_executable: str | None
    telemetry_mode: str | None
    database: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        data.update({
            "network": "none",
            "executes_govulncheck": False,
            "mutates_telemetry_configuration": False,
            "project_mutation": "none",
        })
        return data


def _resolve_executable(
    value: str,
    which: Callable[[str], str | None],
) -> str | None:
    resolved = which(value)
    if resolved:
        # shutil.which already selected the executable from PATH. Preserve that
        # exact spelling instead of reinterpreting foreign paths on this host.
        return str(resolved)
    return None


def preflight_govulncheck_symbol(
    plan: GovulncheckSymbolPlan,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> GovulncheckSymbolPreflight:
    """Inspect whether a pre-public govulncheck symbol plan is safe to execute.

    This function never launches govulncheck and never changes Go telemetry
    configuration. It performs only local filesystem/executable checks plus
    ``go env GOTELEMETRY`` under the plan's no-network/single-module guards.
    """

    reasons: list[str] = []
    project = plan.cwd.expanduser().resolve()
    if not project.is_dir():
        reasons.append(f"Go symbol-analysis project directory is unavailable: {project}")

    database = plan.database.expanduser().resolve()
    if not database.is_dir():
        reasons.append(f"local vulnerability database is unavailable: {database}")

    go_executable = _resolve_executable("go", which)
    if go_executable is None:
        reasons.append("Go executable is not available on PATH")

    requested_govulncheck = plan.argv[0] if plan.argv else "govulncheck"
    govulncheck_executable = _resolve_executable(requested_govulncheck, which)
    if govulncheck_executable is None:
        reasons.append(f"govulncheck executable is not available: {requested_govulncheck}")

    telemetry_mode: str | None = None
    if go_executable is not None and project.is_dir():
        environment = dict(os.environ)
        environment.update(plan.environment)
        try:
            completed = run(
                [go_executable, "env", "GOTELEMETRY"],
                cwd=project,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            reasons.append(f"could not inspect Go telemetry mode: {exc}")
        else:
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                reasons.append(
                    "could not inspect Go telemetry mode"
                    + (f": {detail}" if detail else f" (exit {completed.returncode})")
                )
            else:
                telemetry_mode = (completed.stdout or "").strip() or None
                if telemetry_mode != plan.telemetry_mode_required:
                    reasons.append(
                        "Go telemetry mode must already be "
                        f"{plan.telemetry_mode_required!r}; observed {telemetry_mode!r}. "
                        "UPM will not change telemetry configuration automatically"
                    )

    return GovulncheckSymbolPreflight(
        ready=not reasons,
        project=str(project),
        go_executable=go_executable,
        govulncheck_executable=govulncheck_executable,
        telemetry_mode=telemetry_mode,
        database=str(database),
        reasons=tuple(reasons),
    )
