from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_go_symbol_runtime_fixture import (
    FIXTURE_MODULE,
    FIXTURE_VERSION,
    fixture_go_environment,
    prepare_module_cache,
    write_runtime_fixture,
)
from support_go_vulndb_fixture import FIXTURE_ALIAS, FIXTURE_ID, FIXTURE_SYMBOL
from unified_project_manager.go_symbol_build_selection import (
    compare_go_symbol_build_selection,
)
from unified_project_manager.go_symbol_correlation import correlate_govulncheck_symbols
from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
from unified_project_manager.go_symbol_preflight import preflight_govulncheck_symbol
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan
from unified_project_manager.go_symbol_reporting import build_go_symbol_project_report
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
)


class GoSymbolRealRuntimeTests(unittest.TestCase):
    def _runtime_prerequisites(self) -> tuple[str, str]:
        go = shutil.which("go")
        if not go:
            self.skipTest("Go executable is not available")
        govulncheck = shutil.which("govulncheck")
        if not govulncheck:
            self.skipTest("govulncheck executable is not available; test does not install it")
        telemetry = subprocess.run(
            [go, "env", "GOTELEMETRY"],
            text=True,
            capture_output=True,
            check=False,
        )
        if telemetry.returncode != 0:
            self.skipTest("could not inspect existing Go telemetry mode")
        mode = (telemetry.stdout or "").strip()
        if mode != "off":
            self.skipTest(
                f"Go telemetry mode is {mode!r}, not 'off'; test does not change telemetry settings"
            )
        return go, govulncheck

    def _snapshot(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def _dependency_impact(self) -> dict:
        return {
            "advisory_id": FIXTURE_ALIAS,
            "ecosystem": "Go",
            "package": FIXTURE_MODULE,
            "version": FIXTURE_VERSION,
            "provider": "go-modules",
            "scope": "module-requirement",
            "component": ".:go",
            "paths": [["example.com/app", FIXTURE_MODULE]],
            "evidence": {
                "module": FIXTURE_MODULE,
                "effective_name": FIXTURE_MODULE,
            },
        }

    def test_real_govulncheck_uses_local_db_and_cache_without_project_mutation(self) -> None:
        go, govulncheck = self._runtime_prerequisites()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")

            prepared = prepare_module_cache(fixture, go_executable=go)
            self.assertEqual(prepared.returncode, 0, prepared.stderr or prepared.stdout)
            self.assertTrue((fixture.project / "go.sum").is_file())
            project_before = self._snapshot(fixture.project)

            plan = build_govulncheck_symbol_plan(
                fixture.project,
                fixture.vulnerability_db,
                executable=govulncheck,
            )
            observation_plan = build_go_symbol_source_observation_plan(
                fixture.project,
                executable=go,
            )
            planned = compare_go_symbol_build_selection(plan, observation_plan)
            self.assertTrue(planned.matches, planned.to_dict())

            isolated = fixture_go_environment(fixture)
            # The actual symbol scan remains GOPROXY=off via the plan. These
            # values only pin caches used by Go/govulncheck to the temp fixture.
            inherited = {
                "GOMODCACHE": isolated["GOMODCACHE"],
                "GOCACHE": isolated["GOCACHE"],
            }
            with patch.dict(os.environ, inherited, clear=False):
                preflight = preflight_govulncheck_symbol(plan)
                self.assertTrue(preflight.ready, "; ".join(preflight.reasons))
                execution = execute_govulncheck_symbol(plan, preflight=preflight)

            self.assertTrue(execution.succeeded, execution.error or execution.stderr)
            self.assertEqual(execution.returncode, 0)
            self.assertIsNotNone(execution.report)
            self.assertEqual(execution.report.config.database, fixture.vulnerability_db.resolve().as_uri())
            self.assertTrue(
                any(finding.osv == FIXTURE_ID for finding in execution.report.symbol_findings),
                execution.report.to_dict(),
            )
            matching = [
                finding
                for finding in execution.report.symbol_findings
                if finding.osv == FIXTURE_ID
            ]
            self.assertTrue(any(
                finding.vulnerable_frame is not None
                and finding.vulnerable_frame.symbol == FIXTURE_SYMBOL
                and finding.vulnerable_frame.module == FIXTURE_MODULE
                and finding.vulnerable_frame.version == FIXTURE_VERSION
                for finding in matching
            ))

            correlation = correlate_govulncheck_symbols(
                execution.report,
                [self._dependency_impact()],
                component=".:go",
            )
            self.assertEqual(len(correlation.matches), 1)
            self.assertEqual(correlation.matches[0].advisory_id, FIXTURE_ALIAS)
            self.assertEqual(correlation.matches[0].govulncheck_osv, FIXTURE_ID)
            self.assertEqual(correlation.matches[0].symbol, FIXTURE_SYMBOL)
            self.assertEqual(correlation.unmatched, ())

            project_report = build_go_symbol_project_report(
                fixture.project,
                component=".:go",
                execution=execution,
                dependency_impacts=[self._dependency_impact()],
            )
            self.assertEqual(project_report.correlated_matches, 1)
            self.assertEqual(project_report.unmatched_symbol_findings, 0)
            self.assertFalse(project_report.to_dict()["persisted"])

            self.assertEqual(self._snapshot(fixture.project), project_before)


if __name__ == "__main__":
    unittest.main()
