from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.go_symbol_execution import GovulncheckSymbolExecution
from unified_project_manager.go_symbol_preflight import GovulncheckSymbolPreflight
from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    GovulncheckConfig,
    GovulncheckFinding,
    GovulncheckFrame,
    GovulncheckReport,
    build_govulncheck_symbol_plan,
)
from unified_project_manager.go_symbol_reporting import (
    build_go_symbol_fleet_report,
    build_go_symbol_project_report,
)


class GoSymbolReportingTests(unittest.TestCase):
    def _execution(self, root: Path, *, succeeded: bool, module: str = "example.com/dep") -> GovulncheckSymbolExecution:
        project = root / "project"
        database = root / "vulndb"
        project.mkdir(parents=True, exist_ok=True)
        database.mkdir(parents=True, exist_ok=True)
        plan = build_govulncheck_symbol_plan(project, database)
        preflight = GovulncheckSymbolPreflight(
            ready=True,
            project=str(project.resolve()),
            go_executable="/tools/go",
            govulncheck_executable="/tools/govulncheck",
            telemetry_mode="off",
            database=str(database.resolve()),
            reasons=(),
        )
        if not succeeded:
            return GovulncheckSymbolExecution(
                plan, preflight, 2, None, "analysis failed", "analysis failed", True
            )
        report = GovulncheckReport(
            GovulncheckConfig(
                protocol_version=GOVULNCHECK_PROTOCOL_VERSION,
                scanner_name="govulncheck",
                scanner_version="v1.6.0",
                database=database.resolve().as_uri(),
                database_last_modified=None,
                go_version="go1.24.0",
                scan_level="symbol",
                scan_mode="source",
            ),
            {"GO-2026-0001": ("CVE-2026-1234",)},
            (
                GovulncheckFinding(
                    "GO-2026-0001",
                    "v1.2.4",
                    (
                        GovulncheckFrame(
                            module,
                            "v1.2.3",
                            "example.com/dep/pkg",
                            "Danger",
                            None,
                            {"filename": "pkg/danger.go", "line": 17},
                        ),
                    ),
                ),
            ),
        )
        return GovulncheckSymbolExecution(plan, preflight, 0, report, "", None, True)

    def _impact(self, *, advisory="CVE-2026-1234", module="example.com/dep", component=".:go") -> dict:
        return {
            "advisory_id": advisory,
            "ecosystem": "Go",
            "package": module,
            "version": "v1.2.3",
            "provider": "go-modules",
            "scope": "module-requirement",
            "component": component,
            "paths": [["example.com/app", module]],
            "evidence": {"module": module, "effective_name": module},
        }

    def test_successful_project_report_uses_strict_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            execution = self._execution(root, succeeded=True)
            report = build_go_symbol_project_report(
                execution.plan.cwd,
                component=".:go",
                execution=execution,
                dependency_impacts=[self._impact()],
            )

            self.assertTrue(report.execution_succeeded)
            self.assertIsNotNone(report.correlation)
            self.assertEqual(report.correlated_matches, 1)
            self.assertEqual(report.unmatched_symbol_findings, 0)
            data = report.to_dict()
            self.assertFalse(data["public"])
            self.assertFalse(data["persisted"])
            self.assertEqual(data["runtime_reachability"], "not-evaluated")
            self.assertEqual(data["exploitability"], "not-established")

    def test_successful_execution_with_unmatched_symbol_remains_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            execution = self._execution(root, succeeded=True, module="example.com/other")
            report = build_go_symbol_project_report(
                execution.plan.cwd,
                component=".:go",
                execution=execution,
                dependency_impacts=[self._impact()],
            )

            self.assertTrue(report.execution_succeeded)
            self.assertEqual(report.correlated_matches, 0)
            self.assertEqual(report.unmatched_symbol_findings, 1)
            self.assertIn("effective module", report.correlation.unmatched[0].reason)

    def test_failed_execution_does_not_manufacture_negative_correlation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            execution = self._execution(root, succeeded=False)
            report = build_go_symbol_project_report(
                execution.plan.cwd,
                component=".:go",
                execution=execution,
                dependency_impacts=[self._impact()],
            )

            self.assertFalse(report.execution_succeeded)
            self.assertIsNone(report.correlation)
            self.assertEqual(report.correlated_matches, 0)
            self.assertEqual(report.unmatched_symbol_findings, 0)
            self.assertIsNone(report.to_dict()["correlation"])

    def test_fleet_report_aggregates_without_reexecution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one_root = root / "one"
            two_root = root / "two"
            one_root.mkdir()
            two_root.mkdir()
            one_execution = self._execution(one_root, succeeded=True)
            two_execution = self._execution(two_root, succeeded=False)
            one = build_go_symbol_project_report(
                one_execution.plan.cwd,
                component=".:go",
                execution=one_execution,
                dependency_impacts=[self._impact()],
            )
            two = build_go_symbol_project_report(
                two_execution.plan.cwd,
                component=".:go",
                execution=two_execution,
                dependency_impacts=[self._impact()],
            )

            fleet = build_go_symbol_fleet_report([two, one])
            self.assertEqual(fleet.summary, {
                "projects": 2,
                "execution_succeeded": 1,
                "execution_failed_or_blocked": 1,
                "symbol_findings": 1,
                "correlated_matches": 1,
                "unmatched_symbol_findings": 0,
            })
            self.assertEqual(
                [item.project for item in fleet.projects],
                sorted([one.project, two.project]),
            )
            data = fleet.to_dict()
            self.assertFalse(data["public"])
            self.assertFalse(data["persisted"])

    def test_fleet_keeps_unmatched_counts_separate_from_execution_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matched_root = root / "matched"
            unmatched_root = root / "unmatched"
            failed_root = root / "failed"
            for item in (matched_root, unmatched_root, failed_root):
                item.mkdir()
            matched_execution = self._execution(matched_root, succeeded=True)
            unmatched_execution = self._execution(unmatched_root, succeeded=True, module="example.com/other")
            failed_execution = self._execution(failed_root, succeeded=False)
            reports = [
                build_go_symbol_project_report(
                    matched_execution.plan.cwd, component=".:go", execution=matched_execution,
                    dependency_impacts=[self._impact()],
                ),
                build_go_symbol_project_report(
                    unmatched_execution.plan.cwd, component=".:go", execution=unmatched_execution,
                    dependency_impacts=[self._impact()],
                ),
                build_go_symbol_project_report(
                    failed_execution.plan.cwd, component=".:go", execution=failed_execution,
                    dependency_impacts=[self._impact()],
                ),
            ]
            summary = build_go_symbol_fleet_report(reports).summary
            self.assertEqual(summary["execution_succeeded"], 2)
            self.assertEqual(summary["execution_failed_or_blocked"], 1)
            self.assertEqual(summary["symbol_findings"], 2)
            self.assertEqual(summary["correlated_matches"], 1)
            self.assertEqual(summary["unmatched_symbol_findings"], 1)

    def test_project_path_is_normalized_for_shared_project_fleet_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            execution = self._execution(root, succeeded=True)
            relative = execution.plan.cwd / ".." / "project"
            report = build_go_symbol_project_report(
                relative,
                component=".:go",
                execution=execution,
                dependency_impacts=[self._impact()],
            )
            self.assertEqual(report.project, str(execution.plan.cwd.resolve()))


if __name__ == "__main__":
    unittest.main()
