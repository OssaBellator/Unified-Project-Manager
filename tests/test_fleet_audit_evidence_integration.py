from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.root_entrypoint import main
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.security import SecurityScanResult


class FleetAuditEvidenceIntegrationTests(unittest.TestCase):
    def _project(self, root: Path, name: str) -> None:
        root.mkdir()
        (root / "package.json").write_text(json.dumps({
            "name": name,
            "packageManager": "npm@11",
            "dependencies": {"foo": "1.0.0"},
        }), encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": name, "dependencies": {"foo": "1.0.0"}},
                "node_modules/foo": {"version": "1.0.0"},
            },
        }), encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_applied_fleet_audit_persists_evidence_consumed_by_fleet_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean = root / "clean"
            vulnerable = root / "vulnerable"
            self._project(clean, "clean")
            self._project(vulnerable, "vulnerable")
            registry = root / "projects.json"
            registry.write_text(json.dumps({
                "version": 1,
                "projects": [str(clean), str(vulnerable)],
            }), encoding="utf-8")

            def fake_scan(graph, plan):
                if graph.root.name == "vulnerable":
                    report = {
                        "results": [{
                            "packages": [{
                                "vulnerabilities": [{"id": "OSV-FLEET-1"}],
                            }]
                        }]
                    }
                    return SecurityScanResult(plan, 1, report, bom=cyclonedx_bom(graph))
                return SecurityScanResult(plan, 0, {"results": []}, bom=cyclonedx_bom(graph))

            with patch(
                "unified_project_manager.fleet_security_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                audit_code, audit = self._json([
                    "projects", "audit", "--registry", str(registry), "--apply", "--json"
                ])

            status_code, status = self._json([
                "projects", "status", "--registry", str(registry), "--json"
            ])

            self.assertEqual(audit_code, 1)
            self.assertEqual(audit["summary"]["clean_projects"], 1)
            self.assertEqual(audit["summary"]["vulnerable_projects"], 1)
            self.assertEqual(audit["summary"]["unique_vulnerabilities"], 1)
            self.assertTrue(all(item["evidence_path"] for item in audit["projects"]))

            self.assertEqual(status_code, 1)
            by_path = {item["path"]: item for item in status["projects"]}
            self.assertEqual(
                by_path[str(clean)]["status"]["advisory_evidence"]["state"],
                "current-clean",
            )
            self.assertEqual(
                by_path[str(vulnerable)]["status"]["advisory_evidence"]["state"],
                "current-vulnerable",
            )
            self.assertFalse(by_path[str(clean)]["blocked"])
            self.assertIn("known-vulnerabilities", by_path[str(vulnerable)]["blockers"])


if __name__ == "__main__":
    unittest.main()
