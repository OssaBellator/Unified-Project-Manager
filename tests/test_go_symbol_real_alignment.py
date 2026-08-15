from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_go_symbol_runtime_fixture import (
    fixture_go_environment,
    prepare_module_cache,
    write_runtime_fixture,
)
from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
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
            data = alignment.to_dict()
            self.assertEqual(data["freshness"], "not-established")
            self.assertEqual(data["source_selection_equivalence"], "not-established")
            self.assertEqual(data["build_configuration_equivalence"], "not-established")


if __name__ == "__main__":
    unittest.main()
