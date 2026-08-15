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


class AuditStatusIntegrationTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"npm@11","dependencies":{"foo":"1.0.0"}}',
            encoding="utf-8",
        )
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "app", "dependencies": {"foo": "1.0.0"}},
                "node_modules/foo": {"version": "1.0.0"},
            },
        }), encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_clean_applied_audit_persists_current_status_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            def fake_scan(graph, plan):
                return SecurityScanResult(plan, 0, {"results": []}, bom=cyclonedx_bom(graph))

            with patch(
                "unified_project_manager.security_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                audit_code, audit = self._json(["audit", str(root), "--apply", "--json"])

            status_code, status = self._json(["status", str(root), "--json"])

            self.assertEqual(audit_code, 0)
            self.assertTrue(Path(audit["evidence_path"]).is_file())
            self.assertEqual(audit["evidence"]["inventory_mode"], "static-resolved")
            self.assertEqual(status_code, 0)
            self.assertEqual(status["advisory_evidence"]["state"], "current-clean")
            self.assertNotIn("known-vulnerabilities", status["summary"]["blockers"])

    def test_vulnerable_applied_audit_becomes_status_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            report = {
                "results": [{
                    "packages": [{
                        "package": {"name": "foo", "version": "1.0.0"},
                        "vulnerabilities": [{"id": "OSV-TEST-1"}],
                    }]
                }]
            }

            def fake_scan(graph, plan):
                return SecurityScanResult(plan, 1, report, bom=cyclonedx_bom(graph))

            with patch(
                "unified_project_manager.security_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                audit_code, audit = self._json(["audit", str(root), "--apply", "--json"])

            status_code, status = self._json(["status", str(root), "--json"])

            self.assertEqual(audit_code, 1)
            self.assertEqual(audit["summary"]["vulnerabilities"], 1)
            self.assertEqual(status_code, 1)
            self.assertEqual(status["advisory_evidence"]["state"], "current-vulnerable")
            self.assertIn("known-vulnerabilities", status["summary"]["blockers"])

    def test_preview_does_not_write_advisory_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            code, data = self._json(["audit", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertTrue(data["evidence_will_be_persisted"])
            self.assertFalse((root / ".upm" / "audits" / "osv.json").exists())


if __name__ == "__main__":
    unittest.main()
