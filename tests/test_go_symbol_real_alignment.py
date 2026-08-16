from __future__ import annotations

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
from support_go_vulndb_fixture import FIXTURE_ID, FIXTURE_SYMBOL
from unified_project_manager.go_symbol_build_selection import (
    compare_go_symbol_build_selection,
)
from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
from unified_project_manager.go_symbol_frame_source_alignment import (
    compare_positioned_govulncheck_frame_to_source_observation,
)
from unified_project_manager.go_symbol_frame_source_location import (
    validate_positioned_govulncheck_frame_source_location,
)
from unified_project_manager.go_symbol_preflight import preflight_govulncheck_symbol
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan
from unified_project_manager.go_symbol_scan_alignment import (
    compare_go_symbol_observation_to_scan_sbom,
)
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
)


class GoSymbolRealAlignmentTests(unittest.TestCase):
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

    def test_real_go_observation_and_govulncheck_declared_inventory_align(self) -> None:
        go, govulncheck = self._runtime_prerequisites()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = write_runtime_fixture(Path(temporary) / "fixture")
            prepared = prepare_module_cache(fixture, go_executable=go)
            self.assertEqual(prepared.returncode, 0, prepared.stderr or prepared.stdout)

            isolated = fixture_go_environment(fixture)
            inherited = {
                "GOMODCACHE": isolated["GOMODCACHE"],
                "GOCACHE": isolated["GOCACHE"],
            }
            with patch.dict(os.environ, inherited, clear=False):
                observation_plan = build_go_symbol_source_observation_plan(
                    fixture.project,
                    executable=go,
                )
                observation_execution = execute_go_symbol_source_observation(observation_plan)
                self.assertTrue(
                    observation_execution.succeeded,
                    observation_execution.error or observation_execution.stderr,
                )

                symbol_plan = build_govulncheck_symbol_plan(
                    fixture.project,
                    fixture.vulnerability_db,
                    executable=govulncheck,
                )
                planned = compare_go_symbol_build_selection(symbol_plan, observation_plan)
                self.assertTrue(planned.matches, planned.to_dict())

                preflight = preflight_govulncheck_symbol(symbol_plan)
                self.assertTrue(preflight.ready, "; ".join(preflight.reasons))
                symbol_execution = execute_govulncheck_symbol(
                    symbol_plan,
                    preflight=preflight,
                )
                self.assertTrue(
                    symbol_execution.succeeded,
                    symbol_execution.error or symbol_execution.stderr,
                )

            alignment = compare_go_symbol_observation_to_scan_sbom(
                observation_execution.observation,
                symbol_execution.report,
            )
            self.assertTrue(alignment.roots_match, alignment.to_dict())
            self.assertTrue(alignment.modules_match, alignment.to_dict())
            self.assertTrue(alignment.declared_inventory_match, alignment.to_dict())
            self.assertTrue(alignment.go_version_match, alignment.to_dict())
            data = alignment.to_dict()
            self.assertEqual(data["freshness"], "not-established")
            self.assertEqual(data["source_selection_equivalence"], "not-established")
            self.assertEqual(data["build_configuration_equivalence"], "not-established")

            synthetic_findings = tuple(
                finding
                for finding in symbol_execution.report.symbol_findings
                if finding.osv == FIXTURE_ID
                and finding.vulnerable_frame is not None
                and finding.vulnerable_frame.symbol == FIXTURE_SYMBOL
                and finding.vulnerable_frame.module == FIXTURE_MODULE
                and finding.vulnerable_frame.version == FIXTURE_VERSION
            )
            self.assertEqual(len(synthetic_findings), 1)
            frame_alignment = compare_positioned_govulncheck_frame_to_source_observation(
                synthetic_findings[0].vulnerable_frame,
                observation_execution.observation,
            )
            self.assertTrue(frame_alignment.matched, frame_alignment.to_dict())
            frame_data = frame_alignment.to_dict()
            self.assertEqual(frame_data["source_selection_equivalence"], "not-established")
            self.assertEqual(frame_data["freshness"], "not-established")
            self.assertEqual(frame_data["runtime_reachability"], "not-evaluated")
            self.assertEqual(frame_data["exploitability"], "not-established")

            location = validate_positioned_govulncheck_frame_source_location(
                synthetic_findings[0].vulnerable_frame,
                observation_execution.observation,
            )
            self.assertTrue(location.validated, location.to_dict())
            location_data = location.to_dict()
            self.assertEqual(location_data["source_selection_equivalence"], "not-established")
            self.assertEqual(location_data["build_configuration_equivalence"], "not-established")
            self.assertEqual(location_data["freshness"], "not-established")
            self.assertEqual(location_data["call_graph_freshness"], "not-established")
            self.assertFalse(location_data["source_state_fingerprint"])
            self.assertEqual(location_data["symbol_text_correspondence"], "not-established")
            self.assertFalse(location_data["public"])
            self.assertFalse(location_data["persisted"])
            self.assertEqual(location_data["runtime_reachability"], "not-evaluated")
            self.assertEqual(location_data["exploitability"], "not-established")


if __name__ == "__main__":
    unittest.main()
