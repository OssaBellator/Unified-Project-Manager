from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_project_manager.audit_evidence import build_audit_evidence, write_audit_evidence
from unified_project_manager.audit_status import evaluate_audit_status
from unified_project_manager.discovery import discover
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class AuditStatusTests(unittest.TestCase):
    def _project(self, root: Path, version: str = "1.0.0") -> None:
        (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{"name":"app","version":"1.0.0"},"node_modules/foo":{"version":"' + version + '"}}}',
            encoding="utf-8",
        )

    def _evidence(self, root: Path, *, vulnerable: bool = False, inventory_mode: str = "static-resolved", generated: datetime | None = None) -> None:
        graph = discover(root)
        bom = cyclonedx_bom(graph)
        report = {"results": []}
        returncode = 0
        if vulnerable:
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-test"}],
            }]}]}
            returncode = 1
        result = SecurityScanResult(SecurityScanPlan(root, 1, True, False), returncode, report)
        evidence = build_audit_evidence(
            bom,
            result,
            inventory_mode=inventory_mode,
            now=(lambda: generated) if generated is not None else None,
        )
        write_audit_evidence(root, evidence)

    def test_absent_evidence_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            status = evaluate_audit_status(discover(root))
            self.assertEqual(status.state, "absent")
            self.assertFalse(status.current)
            self.assertFalse(status.passed)

    def test_current_clean_and_vulnerable_states_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clean_root = Path(temporary) / "clean"
            vulnerable_root = Path(temporary) / "vulnerable"
            clean_root.mkdir(); vulnerable_root.mkdir()
            self._project(clean_root); self._project(vulnerable_root)
            self._evidence(clean_root)
            self._evidence(vulnerable_root, vulnerable=True)
            clean = evaluate_audit_status(discover(clean_root))
            vulnerable = evaluate_audit_status(discover(vulnerable_root))
            self.assertEqual(clean.state, "current-clean")
            self.assertTrue(clean.passed)
            self.assertEqual(vulnerable.state, "current-vulnerable")
            self.assertTrue(vulnerable.current)
            self.assertFalse(vulnerable.passed)

    def test_changed_dependencies_make_evidence_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "1.0.0")
            self._evidence(root)
            self._project(root, "2.0.0")
            status = evaluate_audit_status(discover(root))
            self.assertEqual(status.state, "stale")
            self.assertIn("fingerprint", status.reason or "")

    def test_age_budget_is_local_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            generated = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)
            self._evidence(root, generated=generated)
            status = evaluate_audit_status(
                discover(root),
                max_age_seconds=3600,
                now=lambda: generated + timedelta(hours=2),
            )
            self.assertEqual(status.state, "stale")
            self.assertEqual(status.age_seconds, 7200)

    def test_native_inventory_evidence_is_not_silently_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._evidence(root, inventory_mode="native-go-enriched")
            status = evaluate_audit_status(discover(root))
            self.assertEqual(status.state, "native-inventory-unverified")
            self.assertIn("does not re-execute", status.reason or "")


if __name__ == "__main__":
    unittest.main()
