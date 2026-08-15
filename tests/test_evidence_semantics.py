from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.advisory_evidence_v2 import (
    build_advisory_evidence_v2,
    write_advisory_evidence_v2,
)
from unified_project_manager.evidence_manifest import build_evidence_manifest, write_evidence_manifest
from unified_project_manager.evidence_semantics import validate_project_evidence
from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.receipts import (
    build_mutation_receipt,
    capture_project_state,
    write_mutation_receipt,
)


class EvidenceSemanticsTests(unittest.TestCase):
    def _graph(self, root: Path) -> ProjectGraph:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        return ProjectGraph(root, [
            Component("node", root, "npm", manifests=["package.json"]),
        ])

    def _seed_valid_receipt(self, graph: ProjectGraph) -> Path:
        state = capture_project_state(graph)
        receipt = build_mutation_receipt(
            graph.root,
            "sync",
            [{
                "component": ".:node",
                "manager": "npm",
                "cwd": graph.root,
                "argv": ["npm", "ci"],
                "returncode": 0,
            }],
            state,
            state,
            verification={"health_score": 100},
        )
        return write_mutation_receipt(graph.root, receipt)

    def _seed_valid_advisory(self, graph: ProjectGraph) -> Path:
        bom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.7",
            "version": 1,
            "components": [],
        }
        evidence = build_advisory_evidence_v2(
            bom,
            {"results": []},
            scanner_returncode=0,
            inventory_mode="static-resolved",
        )
        return write_advisory_evidence_v2(graph.root, evidence)

    def test_byte_anchored_valid_v2_evidence_passes_semantic_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root)
            self._seed_valid_receipt(graph)
            self._seed_valid_advisory(graph)
            write_evidence_manifest(root, build_evidence_manifest(root))

            validation = validate_project_evidence(root)

            self.assertTrue(validation.valid)
            by_kind = {item.kind: item for item in validation.semantic_checks}
            self.assertTrue(by_kind["mutation-receipt"].valid)
            self.assertEqual(by_kind["mutation-receipt"].assurance, "receipt-v2-verification-bound")
            self.assertTrue(by_kind["advisory-evidence-v2"].valid)

    def test_reanchoring_tampered_advisory_bytes_does_not_make_semantics_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root)
            advisory_path = self._seed_valid_advisory(graph)
            data = json.loads(advisory_path.read_text(encoding="utf-8"))
            data["summary"]["vulnerabilities"] = 1
            data["summary"]["vulnerability_ids"] = ["FAKE"]
            advisory_path.write_text(json.dumps(data), encoding="utf-8")
            # Rebuild the byte manifest after tampering. Byte anchoring alone now
            # agrees with the bad bytes, so the semantic validator must catch it.
            write_evidence_manifest(root, build_evidence_manifest(root))

            validation = validate_project_evidence(root)

            self.assertFalse(validation.valid)
            advisory = next(item for item in validation.semantic_checks if item.kind == "advisory-evidence-v2")
            self.assertFalse(advisory.valid)
            self.assertEqual(advisory.assurance, "self-validating-v2")

    def test_reanchoring_tampered_receipt_bytes_does_not_make_semantics_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = self._graph(root)
            receipt_path = self._seed_valid_receipt(graph)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            data["verification"]["health_score"] = 0
            receipt_path.write_text(json.dumps(data), encoding="utf-8")
            write_evidence_manifest(root, build_evidence_manifest(root))

            validation = validate_project_evidence(root)

            self.assertFalse(validation.valid)
            receipt = next(item for item in validation.semantic_checks if item.kind == "mutation-receipt")
            self.assertFalse(receipt.valid)
            self.assertIn("Receipt ID", receipt.reason or "")

    def test_legacy_advisory_is_hash_bound_but_not_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._graph(root)
            legacy = root / ".upm" / "audits" / "osv.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"version":1,"summary":{"vulnerabilities":0}}\n', encoding="utf-8")
            write_evidence_manifest(root, build_evidence_manifest(root))

            validation = validate_project_evidence(root)

            self.assertTrue(validation.valid)
            item = next(check for check in validation.semantic_checks if check.kind == "advisory-evidence-legacy")
            self.assertIsNone(item.valid)
            self.assertEqual(item.assurance, "hash-bound-compatibility")


if __name__ == "__main__":
    unittest.main()
