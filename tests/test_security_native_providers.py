from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.audit_status import evaluate_audit_status
from unified_project_manager.discovery import discover
from unified_project_manager.native_cyclonedx import NativeCycloneDxInventory
from unified_project_manager.root_entrypoint import main
from unified_project_manager.security import SecurityScanResult, execute_security_scan, plan_security_scan


class NativeProviderSecurityTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8"
        )
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_native_preview_executes_neither_provider_inventory_nor_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            with patch("unified_project_manager.security_entrypoint.execute_security_scan") as execute:
                code, data = self._json(["audit", str(root), "--native", "--json"])

            self.assertEqual(code, 0)
            execute.assert_not_called()
            self.assertFalse(data["executed"])
            self.assertEqual(data["plan"]["inventory_mode"], "native-providers")
            self.assertFalse(data["plan"]["provider_inventory_network"])
            self.assertTrue(data["plan"]["network_may_be_used"])

    def test_execute_native_provider_scan_builds_bom_only_on_apply_and_removes_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            graph = discover(root)
            plan = plan_security_scan(graph, native_providers=True)
            bom = {
                "bomFormat":"CycloneDX","specVersion":"1.7","version":1,
                "components":[{"type":"library","name":"foo","version":"1.0.0","bom-ref":"pkg:npm/foo@1.0.0","purl":"pkg:npm/foo@1.0.0"}],
            }
            build_calls = []
            scanner_paths = []

            def build_native(_graph, **_kwargs):
                build_calls.append(True)
                return NativeCycloneDxInventory(bom, [], [], [], [], [])

            def run(argv, **kwargs):
                scanner_paths.append(Path(argv[-1]))
                self.assertTrue(scanner_paths[-1].is_file())
                scanned = json.loads(scanner_paths[-1].read_text(encoding="utf-8"))
                self.assertEqual(scanned, bom)
                return subprocess.CompletedProcess(argv, 0, '{"results":[]}', "")

            result = execute_security_scan(
                graph,
                plan,
                build_native=build_native,
                run=run,
                which=lambda _name: "/tools/osv-scanner",
            )

            self.assertEqual(build_calls, [True])
            self.assertTrue(result.scanner_succeeded)
            self.assertEqual(result.bom, bom)
            self.assertEqual(len(scanner_paths), 1)
            self.assertFalse(scanner_paths[0].exists())

    def test_public_native_apply_persists_exact_native_inventory_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            bom = {
                "bomFormat":"CycloneDX","specVersion":"1.7","version":1,
                "components":[{"type":"library","name":"foo","version":"1.0.0","bom-ref":"pkg:npm/foo@1.0.0","purl":"pkg:npm/foo@1.0.0"}],
            }

            def execute(_graph, plan):
                return SecurityScanResult(plan, 0, {"results":[]}, "", bom)

            with patch("unified_project_manager.security_entrypoint.execute_security_scan", side_effect=execute):
                code, data = self._json(["audit", str(root), "--native", "--apply", "--json"])

            self.assertEqual(code, 0)
            evidence_path = Path(data["evidence_path"])
            self.assertTrue(evidence_path.is_file())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["inventory_mode"], "native-providers")
            self.assertEqual(evidence["package_count"], 1)
            status = evaluate_audit_status(discover(root))
            self.assertEqual(status.state, "native-inventory-unverified")

    def test_native_provider_scanner_failure_does_not_persist_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            bom = {"bomFormat":"CycloneDX","specVersion":"1.7","version":1,"components":[]}

            def execute(_graph, plan):
                return SecurityScanResult(plan, 2, None, "scanner failed", bom)

            with patch("unified_project_manager.security_entrypoint.execute_security_scan", side_effect=execute):
                code, data = self._json(["audit", str(root), "--native", "--apply", "--json"])

            self.assertEqual(code, 2)
            self.assertIsNone(data["evidence_path"])
            self.assertFalse((root / ".upm" / "audits" / "osv.json").exists())


if __name__ == "__main__":
    unittest.main()
