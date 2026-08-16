from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .go_symbol_reachability import GovulncheckSymbolPlan


PLAN_AUTHORIZATION_SCOPE = "govulncheck-symbol-execution-authorization-v1"


def govulncheck_symbol_plan_authorization_identity(plan: GovulncheckSymbolPlan) -> str:
    """Return a deterministic identity binding preflight to one execution plan.

    This is local execution-authorization metadata only. It is not symbol
    evidence, a source/build-state fingerprint, or a freshness claim.
    """

    payload = {
        "scope": PLAN_AUTHORIZATION_SCOPE,
        "cwd": str(Path(plan.cwd).expanduser().resolve()),
        "database": str(Path(plan.database).expanduser().resolve()),
        "database_uri": plan.database_uri,
        "argv": list(plan.argv),
        "environment": sorted(
            (str(key), str(value)) for key, value in plan.environment.items()
        ),
        "telemetry_mode_required": plan.telemetry_mode_required,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
