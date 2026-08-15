from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.root_entrypoint import main
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class _Evidence:
    def to_dict(self):
        return {"version": 2, "evidence_id": "test"}


class _ImportEvidence:
    def to_dict(self):
        return {
            "advisory_id": "GO-TEST-1",
            "package": "example.com/dep",
            "version": "v1.2.3",
            "component": ".:go",
            "module": "example.com/dep",
            "state": "package-import-reachable",
            "import_path": ["example.com/app/pkg", "example.com/dep/pkg"],
            "returncode": 0,
            "error": None,
            "dependency_paths": [["example.com/app", "example.com/dep"]],
            "provider": "go-mod-why",
            "scope": "package-import-graph",
            "network": "offline",
            "test_imports_may_contribute": True,
            "api_reachability": "not-evaluated",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "persisted": False,
        }


class GoImportReachabilityAuditTests(unittest.TestCase):
    def _plan(self, root: Path) -> SecurityScanPlan:
        return SecurityScanPlan(
            root=root,
            package_count=1,
            package_count_exact=False,
            native_go=False,
            native_providers=True,
        )

    def _vulnerable_result(self, plan: SecurityScanPlan) -> SecurityScanResult:
        report = {
            "results": [{
                "packages": [{
                    "package": {
                        "ecosystem": "Go",
                        "name": "example.com/dep",
                        "version": "v1.2.3",
                    },
                    "vulnerabilities": [{"id": "GO-TEST-1"}],
                }],
            }],
        }
        return SecurityScanResult(
            plan,
            1,
            report=report,
            bom={"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "components": []},
        )

    def _impact(self) -> dict:
        return {
            "advisory_id": "GO-TEST-1",
            "ecosystem": "Go",
            "package": "example.com/dep",
            "version": "v1.2.3",
            "provider": "go-modules",
            "scope": "module-requirement",
            "component": ".:go",
            "paths": [["example.com/app", "example.com/dep"]],
            "evidence": {"module": "example.com/dep", "effective_name": "example.com/dep"},
        }

    def test_project_flag_requires_full_native_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "audit", temporary, "--native-go", "--go-import-reachability", "--json"
                ])
            self.assertEqual(code, 2)
            self.assertIn("requires --native", json.loads(output.getvalue())["error"])

    def test_fleet_flag_requires_full_native_inventory(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["projects", "audit", "--go-import-reachability", "--json"])
        self.assertEqual(code, 2)
        self.assertIn("requires --native", json.loads(output.getvalue())["error"])

    def test_project_preview_reports_enrichment_without_executing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            output = io.StringIO()
            with (
                patch("unified_project_manager.security_entrypoint.plan_security_scan", return_value=plan),
                patch("unified_project_manager.security_entrypoint.execute_security_scan") as execute,
                patch("unified_project_manager.security_entrypoint.collect_go_import_reachability") as collect,
                redirect_stdout(output),
            ):
                code = main([
                    "audit", str(root), "--native", "--go-import-reachability", "--json"
                ])

            self.assertEqual(code, 0)
            execute.assert_not_called()
            collect.assert_not_called()
            data = json.loads(output.getvalue())
            self.assertTrue(data["go_import_reachability"]["requested"])
            self.assertFalse(data["go_import_reachability"]["executed"])
            self.assertEqual(data["go_import_reachability"]["network"], "offline")
            self.assertFalse(data["go_import_reachability"]["persisted"])

    def test_applied_project_audit_returns_separate_import_reachability_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            result = self._vulnerable_result(plan)
            output = io.StringIO()
            with (
                patch("unified_project_manager.security_entrypoint.plan_security_scan", return_value=plan),
                patch("unified_project_manager.security_entrypoint.execute_security_scan", return_value=result),
                patch("unified_project_manager.security_entrypoint._dependency_impacts", return_value=([self._impact()], None)),
                patch(
                    "unified_project_manager.security_entrypoint.collect_go_import_reachability",
                    return_value=[_ImportEvidence()],
                ) as collect,
                patch("unified_project_manager.security_entrypoint.build_audit_evidence", return_value=_Evidence()),
                patch(
                    "unified_project_manager.security_entrypoint.write_audit_evidence",
                    return_value=root / ".upm" / "audits" / "osv.json",
                ),
                redirect_stdout(output),
            ):
                code = main([
                    "audit", str(root), "--native", "--go-import-reachability", "--apply", "--json"
                ])

            self.assertEqual(code, 1)
            collect.assert_called_once()
            data = json.loads(output.getvalue())
            self.assertEqual(len(data["dependency_impacts"]), 1)
            self.assertEqual(len(data["go_import_reachability"]), 1)
            source = data["go_import_reachability"][0]
            self.assertEqual(source["state"], "package-import-reachable")
            self.assertEqual(source["api_reachability"], "not-evaluated")
            self.assertEqual(source["runtime_reachability"], "not-evaluated")
            self.assertEqual(source["exploitability"], "not-established")
            self.assertFalse(source["persisted"])


if __name__ == "__main__":
    unittest.main()
