from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.advisory_evidence_v2 import build_advisory_evidence_v2, write_advisory_evidence_v2
from unified_project_manager.evidence_manifest import build_evidence_manifest, write_evidence_manifest
from unified_project_manager.evidence_semantics_entrypoint import main


class EvidenceSemanticsEntrypointTests(unittest.TestCase):
    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_valid_v2_evidence_manifest_is_zero_and_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = build_advisory_evidence_v2(
                {"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "components": []},
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            write_advisory_evidence_v2(root, evidence)
            write_evidence_manifest(root, build_evidence_manifest(root))

            code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertTrue(data["valid"])
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["scanner_execution"])
            self.assertFalse(data["native_provider_execution"])
            self.assertFalse(data["mutation_executed"])

    def test_semantically_invalid_but_reanchored_evidence_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = build_advisory_evidence_v2(
                {"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "components": []},
                {"results": []},
                scanner_returncode=0,
                inventory_mode="static-resolved",
            )
            path = write_advisory_evidence_v2(root, evidence)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["summary"]["vulnerabilities"] = 1
            data["summary"]["vulnerability_ids"] = ["FAKE"]
            path.write_text(json.dumps(data), encoding="utf-8")
            write_evidence_manifest(root, build_evidence_manifest(root))

            code, result = self._json([str(root), "--json"])

            self.assertEqual(code, 1)
            self.assertFalse(result["valid"])
            invalid = [item for item in result["semantic_checks"] if item["valid"] is False]
            self.assertEqual(invalid[0]["kind"], "advisory-evidence-v2")

    def test_missing_manifest_is_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, data = self._json([str(root), "--json"])
            self.assertEqual(code, 1)
            self.assertFalse(data["valid"])
            self.assertIn("manifest", data["reason"].lower())


if __name__ == "__main__":
    unittest.main()
