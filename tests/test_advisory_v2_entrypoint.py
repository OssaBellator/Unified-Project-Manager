from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.advisory_v2_entrypoint import main
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.security import SecurityScanResult


class AdvisoryV2EntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
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

    def test_preview_writes_no_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(data["evidence_version"], 2)
            self.assertFalse((root / ".upm" / "audits" / "osv-v2.json").exists())

    def test_clean_apply_persists_valid_v2_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_scan(graph, plan):
                return SecurityScanResult(plan, 0, {"results": []}, bom=cyclonedx_bom(graph))

            with patch(
                "unified_project_manager.advisory_v2_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                code, data = self._json([str(root), "--apply", "--json"])

            self.assertEqual(code, 0)
            self.assertTrue(data["validation"]["valid"])
            self.assertEqual(data["evidence"]["version"], 2)
            self.assertEqual(data["evidence"]["summary"]["vulnerabilities"], 0)
            self.assertTrue(Path(data["evidence_path"]).is_file())

    def test_vulnerable_apply_returns_one_and_binds_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            report = {
                "results": [{
                    "packages": [{
                        "package": {"name": "foo", "version": "1.0.0"},
                        "vulnerabilities": [{"id": "OSV-V2-1"}],
                    }]
                }]
            }

            def fake_scan(graph, plan):
                return SecurityScanResult(plan, 1, report, bom=cyclonedx_bom(graph))

            with patch(
                "unified_project_manager.advisory_v2_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                code, data = self._json([str(root), "--apply", "--json"])

            self.assertEqual(code, 1)
            self.assertTrue(data["validation"]["valid"])
            self.assertEqual(data["evidence"]["summary"]["vulnerability_ids"], ["OSV-V2-1"])
            self.assertEqual(data["evidence"]["scanner_returncode"], 1)

    def test_scanner_failure_writes_no_v2_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_scan(_graph, plan):
                return SecurityScanResult(plan, 127, None, stderr="scanner unavailable")

            with patch(
                "unified_project_manager.advisory_v2_entrypoint.execute_security_scan",
                side_effect=fake_scan,
            ):
                code, data = self._json([str(root), "--apply", "--json"])

            self.assertEqual(code, 2)
            self.assertIsNone(data["evidence"])
            self.assertFalse((root / ".upm" / "audits" / "osv-v2.json").exists())


if __name__ == "__main__":
    unittest.main()
