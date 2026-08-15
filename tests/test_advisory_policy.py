from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.audit_evidence import build_audit_evidence, write_audit_evidence
from unified_project_manager.discovery import discover
from unified_project_manager.policy import evaluate_policy
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.security import SecurityScanPlan, SecurityScanResult


class AdvisoryPolicyTests(unittest.TestCase):
    def _project(self, root: Path, version: str = "1.0.0") -> None:
        (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{"name":"app","version":"1.0.0"},"node_modules/foo":{"version":"' + version + '"}}}',
            encoding="utf-8",
        )

    def _save(self, root: Path, vulnerable: bool = False) -> None:
        graph = discover(root)
        bom = cyclonedx_bom(graph)
        report = {"results": []}
        code = 0
        if vulnerable:
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-test"}],
            }]}]}
            code = 1
        result = SecurityScanResult(SecurityScanPlan(root, 1, True, False), code, report)
        write_audit_evidence(root, build_audit_evidence(bom, result))

    def test_policy_can_require_current_local_evidence_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            (root / "upm.toml").write_text('[policy]\nrequire_advisory_evidence=true\n', encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.advisory-evidence-required", {item.code for item in report.violations})
            self._save(root)
            self.assertTrue(evaluate_policy(discover(root)).passed)

    def test_known_vulnerability_budget_uses_persisted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            self._save(root, vulnerable=True)
            (root / "upm.toml").write_text('[policy]\nmax_known_vulnerabilities=0\n', encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.advisory-budget-exceeded", {item.code for item in report.violations})

    def test_stale_evidence_cannot_satisfy_vulnerability_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root, "1.0.0")
            self._save(root)
            self._project(root, "2.0.0")
            (root / "upm.toml").write_text('[policy]\nmax_known_vulnerabilities=0\n', encoding="utf-8")
            report = evaluate_policy(discover(root))
            self.assertIn("policy.advisory-evidence-unavailable", {item.code for item in report.violations})


if __name__ == "__main__":
    unittest.main()
