from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from unified_project_manager.go_symbol_execution import _preflight_matches_plan
from unified_project_manager.go_symbol_plan_authorization import (
    govulncheck_symbol_plan_authorization_identity,
)
from unified_project_manager.go_symbol_preflight import preflight_govulncheck_symbol
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan


class GoSymbolPlanAuthorizationTests(unittest.TestCase):
    def _plan(self, root: Path):
        project = root / "project"
        database = root / "vulndb"
        project.mkdir()
        database.mkdir()
        return build_govulncheck_symbol_plan(project, database, executable="govulncheck")

    def _preflight(self, plan):
        def which(name: str) -> str | None:
            if name == "go":
                return "/tools/go"
            if name == "govulncheck":
                return "/tools/govulncheck"
            return None

        return preflight_govulncheck_symbol(
            plan,
            run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "off\n", ""),
            which=which,
        )

    def test_identity_is_deterministic_across_environment_insertion_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            reversed_environment = dict(reversed(tuple(plan.environment.items())))
            reordered = replace(plan, environment=reversed_environment)
            self.assertEqual(
                govulncheck_symbol_plan_authorization_identity(plan),
                govulncheck_symbol_plan_authorization_identity(reordered),
            )

    def test_identity_changes_with_safety_relevant_plan_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            baseline = govulncheck_symbol_plan_authorization_identity(plan)
            variants = (
                replace(plan, argv=(*plan.argv[:-1], "./cmd/...")),
                replace(plan, environment={**plan.environment, "GOPROXY": "https://proxy.invalid"}),
                replace(plan, database_uri="file:///different-db"),
                replace(plan, telemetry_mode_required="local"),
            )
            for variant in variants:
                with self.subTest(variant=variant):
                    self.assertNotEqual(
                        baseline,
                        govulncheck_symbol_plan_authorization_identity(variant),
                    )

    def test_preflight_records_authorization_identity_without_freshness_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            preflight = self._preflight(plan)
            self.assertTrue(preflight.ready, preflight.reasons)
            self.assertEqual(
                preflight.plan_authorization_identity,
                govulncheck_symbol_plan_authorization_identity(plan),
            )
            data = preflight.to_dict()
            self.assertTrue(data["authorization_only"])
            self.assertEqual(data["freshness"], "not-established")

    def test_preflight_identity_fails_closed_on_stale_or_missing_plan_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            preflight = self._preflight(plan)

            stale_argv = replace(plan, argv=(*plan.argv[:-1], "./cmd/..."))
            self.assertIn(
                "authorization identity does not match",
                _preflight_matches_plan(stale_argv, preflight) or "",
            )

            stale_environment = replace(
                plan,
                environment={**plan.environment, "GOPROXY": "https://proxy.invalid"},
            )
            self.assertIn(
                "authorization identity does not match",
                _preflight_matches_plan(stale_environment, preflight) or "",
            )

            missing = replace(preflight, plan_authorization_identity=None)
            self.assertIn(
                "missing its execution-plan authorization identity",
                _preflight_matches_plan(plan, missing) or "",
            )


if __name__ == "__main__":
    unittest.main()
