from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.audit_evidence import (
    AuditEvidenceError,
    audit_evidence_matches,
    build_audit_evidence,
    load_audit_evidence,
    write_audit_evidence,
)
from unified_project_manager.discovery import discover
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class AuditEvidenceTests(unittest.TestCase):
    def _project(self, root: Path, version: str = "1.0.0") -> None:
        (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(json.dumps({
            "lockfileVersion": 3,
            "packages": {
                "": {"name":"app","version":"1.0.0"},
                "node_modules/foo": {"version": version},
            },
        }), encoding="utf-8")

    def test_evidence_round_trip_matches_exact_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            bom = cyclonedx_bom(discover(root))
            result = SecurityScanResult(
                SecurityScanPlan(root, 1, True, False),
                0,
                {"results": []},
            )
            evidence = build_audit_evidence(
                bom,
                result,
                now=lambda: datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc),
            )
            path = write_audit_evidence(root, evidence)
            loaded = load_audit_evidence(root)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(path, root / ".upm" / "audits" / "osv.json")
            self.assertEqual(loaded.generated_at, "2026-08-15T02:00:00Z")
            self.assertTrue(audit_evidence_matches(loaded, bom))

    def test_dependency_change_invalidates_prior_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "1.0.0")
            bom = cyclonedx_bom(discover(root))
            evidence = build_audit_evidence(
                bom,
                SecurityScanResult(SecurityScanPlan(root, 1, True, False), 0, {"results": []}),
            )
            write_audit_evidence(root, evidence)

            self._project(root, "2.0.0")
            changed_bom = cyclonedx_bom(discover(root))
            loaded = load_audit_evidence(root)
            assert loaded is not None
            self.assertFalse(audit_evidence_matches(loaded, changed_bom))

    def test_vulnerability_summary_is_persisted_without_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            bom = cyclonedx_bom(discover(root))
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-test"}],
            }]}]}
            result = SecurityScanResult(SecurityScanPlan(root, 1, True, False), 1, report)
            evidence = build_audit_evidence(bom, result)
            self.assertTrue(evidence.vulnerable)
            self.assertEqual(evidence.scanner_returncode, 1)
            self.assertEqual(evidence.vulnerabilities, 1)
            self.assertEqual(evidence.affected_packages, 1)

    def test_invalid_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / ".upm" / "audits" / "osv.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"version":999}', encoding="utf-8")
            with self.assertRaisesRegex(AuditEvidenceError, "Unsupported"):
                load_audit_evidence(root)


if __name__ == "__main__":
    unittest.main()
