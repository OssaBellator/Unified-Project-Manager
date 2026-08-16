from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.go_symbol_build_selection import compare_go_symbol_build_selection
from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
from unified_project_manager.go_symbol_plan_authorization import (
    govulncheck_symbol_plan_authorization_identity,
)
from unified_project_manager.go_symbol_preflight import GovulncheckSymbolPreflight
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
)


class GoSymbolGoEnvPlanNormalizationTests(unittest.TestCase):
    def _plans(self, root: Path, *, goflags: str = ""):
        project = root / "project"
        database = root / "vulndb"
        project.mkdir()
        database.mkdir()
        with patch.dict(os.environ, {"GOFLAGS": goflags}, clear=False):
            return (
                build_govulncheck_symbol_plan(project, database, executable="/tools/govulncheck"),
                build_go_symbol_source_observation_plan(project, executable="/tools/go"),
            )

    def test_default_plans_disable_persisted_go_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            self.assertEqual(scanner.environment["GOENV"], "off")
            self.assertEqual(observation.environment["GOENV"], "off")
            self.assertEqual(scanner.environment["GOFLAGS"], "")
            self.assertEqual(observation.environment["GOFLAGS"], "")
            self.assertTrue(compare_go_symbol_build_selection(scanner, observation).matches)

    def test_build_selection_requires_goenv_match_and_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))

            observation_without_goenv = replace(
                observation,
                environment={
                    key: value
                    for key, value in observation.environment.items()
                    if key != "GOENV"
                },
            )
            mismatch = compare_go_symbol_build_selection(scanner, observation_without_goenv)
            self.assertFalse(mismatch.matches)
            self.assertIn("GOENV environment differs", mismatch.differences)

            scanner_persisted = replace(
                scanner,
                environment={**scanner.environment, "GOENV": "/tmp/persisted-goenv"},
            )
            observation_persisted = replace(
                observation,
                environment={**observation.environment, "GOENV": "/tmp/persisted-goenv"},
            )
            unsafe = compare_go_symbol_build_selection(scanner_persisted, observation_persisted)
            self.assertFalse(unsafe.matches)
            self.assertIn("GOENV environment is not normalized", unsafe.differences)

    def test_build_selection_detects_process_goflags_drift_between_plan_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            database = root / "vulndb"
            project.mkdir()
            database.mkdir()
            with patch.dict(os.environ, {"GOFLAGS": ""}, clear=False):
                observation = build_go_symbol_source_observation_plan(
                    project, executable="/tools/go"
                )
            with patch.dict(os.environ, {"GOFLAGS": "-tags=ambient"}, clear=False):
                scanner = build_govulncheck_symbol_plan(
                    project, database, executable="/tools/govulncheck"
                )

            alignment = compare_go_symbol_build_selection(scanner, observation)
            self.assertFalse(alignment.matches)
            self.assertIn("GOFLAGS environment differs", alignment.differences)

    def test_nonempty_captured_process_goflags_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(
                Path(temporary), goflags="-tags=ambient"
            )
            alignment = compare_go_symbol_build_selection(scanner, observation)
            self.assertFalse(alignment.matches)
            self.assertIn("GOFLAGS environment is not normalized", alignment.differences)

    def test_source_observation_uses_planned_goflags_and_disables_ambient_goenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            with patch.dict(
                os.environ,
                {"GOENV": "/tmp/persisted-goenv", "GOFLAGS": "-tags=planned"},
                clear=False,
            ):
                plan = build_go_symbol_source_observation_plan(
                    project, executable="/tools/go"
                )
            calls = []

            env_payload = json.dumps({
                "GOOS": "linux",
                "GOARCH": "amd64",
                "GOVERSION": "go1.24.0",
                "GOFLAGS": "-tags=planned",
            })
            package_payload = json.dumps({
                "Dir": str(project.resolve()),
                "ImportPath": "example.com/app",
                "Name": "main",
                "Module": {"Path": "example.com/app", "Main": True},
                "GoFiles": ["main.go"],
                "CompiledGoFiles": ["main.go"],
            })

            def run(argv, **kwargs):
                calls.append(kwargs["env"])
                if argv[1:3] == ["env", "-json"]:
                    return subprocess.CompletedProcess(argv, 0, env_payload, "")
                return subprocess.CompletedProcess(argv, 0, package_payload, "")

            with patch.dict(
                os.environ,
                {"GOENV": "/tmp/later-goenv", "GOFLAGS": "-tags=later"},
                clear=False,
            ):
                result = execute_go_symbol_source_observation(
                    plan,
                    run=run,
                    which=lambda _name: "/tools/go",
                )

            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(len(calls), 2)
            for environment in calls:
                self.assertEqual(environment["GOENV"], "off")
                self.assertEqual(environment["GOFLAGS"], "-tags=planned")

    def test_scanner_execution_uses_planned_goflags_and_disables_ambient_goenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            database = root / "vulndb"
            project.mkdir()
            database.mkdir()
            with patch.dict(
                os.environ,
                {"GOENV": "/tmp/persisted-goenv", "GOFLAGS": "-tags=planned"},
                clear=False,
            ):
                scanner = build_govulncheck_symbol_plan(
                    project, database, executable="/tools/govulncheck"
                )
            preflight = GovulncheckSymbolPreflight(
                ready=True,
                project=str(scanner.cwd),
                go_executable="/tools/go",
                govulncheck_executable="/tools/govulncheck",
                telemetry_mode="off",
                database=str(scanner.database),
                reasons=(),
                plan_authorization_identity=govulncheck_symbol_plan_authorization_identity(scanner),
            )
            captured = []
            output = "\n".join([
                json.dumps({
                    "config": {
                        "protocol_version": "v1.0.0",
                        "scanner_name": "govulncheck",
                        "scanner_version": "v1.6.0",
                        "db": scanner.database_uri,
                        "go_version": "go1.24.0",
                        "scan_level": "symbol",
                        "scan_mode": "source",
                    }
                }),
                json.dumps({
                    "SBOM": {
                        "go_version": "go1.24.0",
                        "modules": [{"path": "example.com/app"}],
                        "roots": ["example.com/app"],
                    }
                }),
            ])

            def run(argv, **kwargs):
                captured.append(kwargs["env"])
                return subprocess.CompletedProcess(argv, 0, output, "")

            with patch.dict(
                os.environ,
                {"GOENV": "/tmp/later-goenv", "GOFLAGS": "-tags=later"},
                clear=False,
            ):
                result = execute_govulncheck_symbol(scanner, preflight=preflight, run=run)

            self.assertTrue(result.succeeded, result.error)
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["GOENV"], "off")
            self.assertEqual(captured[0]["GOFLAGS"], "-tags=planned")


if __name__ == "__main__":
    unittest.main()
