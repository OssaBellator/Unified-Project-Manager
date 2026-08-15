from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.audit_evidence import load_audit_evidence
from unified_project_manager.audited_security import execute_and_persist_security_scan
from unified_project_manager.discovery import discover
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class AuditedSecurityTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {"": {}, "node_modules/foo": {"version": "1.0.0"}},
        }), encoding="utf-8")

    def test_clean_and_vulnerable_scans_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            plan = SecurityScanPlan(root, 1, True, False)
            vulnerable = SecurityScanResult(
                plan,
                1,
                {"results": [{"packages": [{"vulnerabilities": [{"id": "GHSA-x"}]}]}]},
            )
            result = execute_and_persist_security_scan(
                graph,
                plan,
                execute_scan=lambda *args, **kwargs: vulnerable,
            )
            self.assertIsNotNone(result.evidence_path)
            evidence = load_audit_evidence(root)
            self.assertIsNotNone(evidence)
            assert evidence is not None
            self.assertTrue(evidence.vulnerable)

    def test_scanner_failure_is_not_persisted_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            plan = SecurityScanPlan(root, 1, True, False)
            failed = SecurityScanResult(plan, 127, None, "missing")
            result = execute_and_persist_security_scan(
                graph,
                plan,
                execute_scan=lambda *args, **kwargs: failed,
            )
            self.assertIsNone(result.evidence_path)
            self.assertIsNone(load_audit_evidence(root))


if __name__ == "__main__":
    unittest.main()
