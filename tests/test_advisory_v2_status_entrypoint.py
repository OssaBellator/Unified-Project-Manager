from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.advisory_evidence_v2 import build_advisory_evidence_v2, write_advisory_evidence_v2
from unified_project_manager.advisory_v2_status_entrypoint import main
from unified_project_manager.discovery import discover
from unified_project_manager.sbom import cyclonedx_bom


class AdvisoryV2StatusEntrypointTests(unittest.TestCase):
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

    def test_absent_is_nonzero_but_performs_no_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            code, data = self._json([str(root), "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(data["state"], "absent")
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["scanner_execution"])
            self.assertFalse(data["native_provider_execution"])

    def test_current_clean_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            write_advisory_evidence_v2(root, evidence)

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["state"], "current-clean")
            self.assertTrue(data["valid"])
            self.assertTrue(data["current"])

    def test_current_vulnerable_is_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            report = {
                "results": [{
                    "packages": [{
                        "vulnerabilities": [{"id": "OSV-STATUS-1"}],
                    }]
                }]
            }
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                report,
                scanner_returncode=1,
                inventory_mode="static-resolved",
            )
            write_advisory_evidence_v2(root, evidence)

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(data["state"], "current-vulnerable")
            self.assertEqual(data["vulnerability_ids"], ["OSV-STATUS-1"])

    def test_tampered_evidence_returns_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            graph = discover(root)
            evidence = build_advisory_evidence_v2(
                cyclonedx_bom(graph),
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            path = write_advisory_evidence_v2(root, evidence)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["report_sha256"] = "0" * 64
            path.write_text(json.dumps(data), encoding="utf-8")

            code, status = self._json([str(root), "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(status["state"], "invalid")


if __name__ == "__main__":
    unittest.main()
