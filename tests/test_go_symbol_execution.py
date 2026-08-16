from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.go_symbol_execution import execute_govulncheck_symbol
from unified_project_manager.go_symbol_plan_authorization import (
    govulncheck_symbol_plan_authorization_identity,
)
from unified_project_manager.go_symbol_preflight import GovulncheckSymbolPreflight
from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    build_govulncheck_symbol_plan,
)


class GoSymbolExecutionTests(unittest.TestCase):
    def _plan(self, root: Path):
        project = root / "project"
        database = root / "vulndb"
        project.mkdir()
        database.mkdir()
        return build_govulncheck_symbol_plan(
            project,
            database,
            executable="govulncheck",
        )

    def _preflight(self, plan, *, ready=True, reasons=(), project=None, database=None, executable="/tools/govulncheck"):
        return GovulncheckSymbolPreflight(
            ready=ready,
            project=project or str(plan.cwd),
            go_executable=str(Path("tools/go").resolve()),
            govulncheck_executable=executable,
            telemetry_mode="off" if ready else "local",
            database=database or str(plan.database),
            reasons=tuple(reasons),
            plan_authorization_identity=govulncheck_symbol_plan_authorization_identity(plan),
        )

    def _stream(self, plan, *, symbol=True, database_uri=None):
        messages = [
            {
                "config": {
                    "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                    "scanner_name": "govulncheck",
                    "scanner_version": "v1.6.0",
                    "db": database_uri or plan.database_uri,
                    "scan_level": "symbol",
                    "scan_mode": "source",
                }
            },
            {
                "SBOM": {
                    "go_version": "go1.24.0",
                    "modules": [
                        {"path": "example.com/app"},
                        {"path": "example.com/dep", "version": "v1.2.3"},
                    ],
                    "roots": ["example.com/app"],
                }
            },
        ]
        if symbol:
            messages.extend([
                {"osv": {"id": "GO-2026-0001", "aliases": ["CVE-2026-1234"]}},
                {"finding": {
                    "osv": "GO-2026-0001",
                    "trace": [{
                        "module": "example.com/dep",
                        "version": "v1.2.3",
                        "package": "example.com/dep/pkg",
                        "function": "Danger",
                    }],
                }},
            ])
        return "\n".join(json.dumps(message) for message in messages)

    def test_json_vulnerability_findings_are_success_not_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            preflight = self._preflight(plan)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, self._stream(plan, symbol=True), "warning")

            result = execute_govulncheck_symbol(plan, preflight=preflight, run=run)

            self.assertTrue(result.succeeded)
            self.assertTrue(result.launched)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.symbol_findings, 1)
            self.assertEqual(result.vulnerability_records, 1)
            self.assertEqual(result.stderr, "warning")
            self.assertIsNone(result.error)
            self.assertIsNotNone(result.report.sbom)
            self.assertTrue(result.report.sbom.has_module("example.com/dep", "v1.2.3"))
            self.assertEqual(len(calls), 1)
            argv, kwargs = calls[0]
            self.assertEqual(argv[0], "/tools/govulncheck")
            self.assertEqual(argv[1:], list(plan.argv[1:]))
            self.assertEqual(kwargs["cwd"], plan.cwd)
            self.assertEqual(kwargs["env"]["GOPROXY"], "off")
            self.assertEqual(kwargs["env"]["GOWORK"], "off")
            self.assertEqual(kwargs["env"]["GOSUMDB"], "off")
            self.assertEqual(kwargs["env"]["GOTOOLCHAIN"], "local")
            data = result.to_dict()
            self.assertFalse(data["public"])
            self.assertFalse(data["persisted"])
            self.assertEqual(data["runtime_reachability"], "not-evaluated")
            self.assertEqual(data["exploitability"], "not-established")

    def test_clean_json_execution_is_also_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=lambda argv, **kwargs: subprocess.CompletedProcess(
                    argv, 0, self._stream(plan, symbol=False), ""
                ),
            )
            self.assertTrue(result.succeeded)
            self.assertEqual(result.symbol_findings, 0)
            self.assertEqual(result.vulnerability_records, 0)
            self.assertEqual(result.report.sbom.roots, ("example.com/app",))

    def test_nonzero_exit_is_execution_failure_and_is_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=lambda argv, **kwargs: subprocess.CompletedProcess(
                    argv, 2, self._stream(plan, symbol=True), "analysis failed"
                ),
            )
            self.assertFalse(result.succeeded)
            self.assertTrue(result.launched)
            self.assertEqual(result.returncode, 2)
            self.assertIsNone(result.report)
            self.assertIn("exit code 2", result.error or "")
            self.assertIn("analysis failed", result.error or "")

    def test_zero_exit_with_invalid_json_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "not-json", ""),
            )
            self.assertFalse(result.succeeded)
            self.assertTrue(result.launched)
            self.assertEqual(result.returncode, 0)
            self.assertIsNone(result.report)
            self.assertIn("JSON evidence is invalid", result.error or "")

    def test_zero_exit_missing_scan_sbom_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            stream = json.dumps({
                "config": {
                    "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                    "db": plan.database_uri,
                    "scan_level": "symbol",
                    "scan_mode": "source",
                }
            })
            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stream, ""),
            )
            self.assertFalse(result.succeeded)
            self.assertIn("missing its scan SBOM", result.error or "")

    def test_reported_database_must_equal_planned_local_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            other = (Path(temporary) / "other-db")
            other.mkdir()
            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=lambda argv, **kwargs: subprocess.CompletedProcess(
                    argv, 0, self._stream(plan, database_uri=other.resolve().as_uri()), ""
                ),
            )
            self.assertFalse(result.succeeded)
            self.assertIsNone(result.report)
            self.assertIn("different from the planned local database", result.error or "")

    def test_not_ready_preflight_blocks_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))

            def run(*_args, **_kwargs):
                raise AssertionError("govulncheck must not launch when preflight is not ready")

            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan, ready=False, reasons=("telemetry is local",)),
                run=run,
            )
            self.assertFalse(result.succeeded)
            self.assertFalse(result.launched)
            self.assertIsNone(result.returncode)
            self.assertIn("telemetry is local", result.error or "")

    def test_mismatched_ready_preflight_blocks_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            other_project = root / "other-project"
            other_project.mkdir()

            def run(*_args, **_kwargs):
                raise AssertionError("mismatched preflight must not authorize execution")

            project_mismatch = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan, project=str(other_project.resolve())),
                run=run,
            )
            self.assertFalse(project_mismatch.launched)
            self.assertIn("preflight project does not match", project_mismatch.error or "")

            other_db = root / "other-db"
            other_db.mkdir()
            database_mismatch = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan, database=str(other_db.resolve())),
                run=run,
            )
            self.assertFalse(database_mismatch.launched)
            self.assertIn("preflight vulnerability database does not match", database_mismatch.error or "")

    def test_oserror_after_ready_preflight_is_explicit_launch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))

            def run(*_args, **_kwargs):
                raise OSError("exec format error")

            result = execute_govulncheck_symbol(
                plan,
                preflight=self._preflight(plan),
                run=run,
            )
            self.assertFalse(result.succeeded)
            self.assertTrue(result.launched)
            self.assertEqual(result.returncode, 127)
            self.assertIn("exec format error", result.error or "")

    def test_ready_preflight_without_resolved_executable_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            preflight = self._preflight(plan, executable=None)

            def run(*_args, **_kwargs):
                raise AssertionError("missing executable must block execution")

            result = execute_govulncheck_symbol(plan, preflight=preflight, run=run)
            self.assertFalse(result.launched)
            self.assertIn("without a resolved govulncheck executable", result.error or "")


if __name__ == "__main__":
    unittest.main()
