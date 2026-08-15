from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.receipt_history import validate_receipt_file
from unified_project_manager.receipts import (
    build_mutation_receipt,
    capture_project_state,
    write_mutation_receipt,
)


class ReceiptV2IntegrityTests(unittest.TestCase):
    def test_verification_tamper_invalidates_v2_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            graph = ProjectGraph(root, [
                Component("node", root, "npm", manifests=["package.json"]),
            ])
            before = capture_project_state(graph)
            after = capture_project_state(graph)
            receipt = build_mutation_receipt(
                root,
                "sync",
                [{
                    "component": ".:node",
                    "manager": "npm",
                    "cwd": root,
                    "argv": ["npm", "ci"],
                    "returncode": 0,
                }],
                before,
                after,
                verification={
                    "health_score": 100,
                    "summary": {"errors": 0, "warnings": 0, "infos": 0},
                },
            )
            path = write_mutation_receipt(root, receipt)
            valid = validate_receipt_file(path)
            self.assertTrue(valid.valid)
            self.assertEqual(valid.version, 2)

            data = json.loads(path.read_text(encoding="utf-8"))
            data["verification"]["health_score"] = 0
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            tampered = validate_receipt_file(path)
            self.assertFalse(tampered.valid)
            self.assertIn("Receipt ID", tampered.reason or "")

    def test_v2_receipt_id_changes_when_verification_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            graph = ProjectGraph(root, [
                Component("node", root, "npm", manifests=["package.json"]),
            ])
            state = capture_project_state(graph)
            commands = [{
                "component": ".:node",
                "manager": "npm",
                "cwd": root,
                "argv": ["npm", "ci"],
                "returncode": 0,
            }]
            first = build_mutation_receipt(
                root,
                "sync",
                commands,
                state,
                state,
                verification={"health_score": 100},
            )
            second = build_mutation_receipt(
                root,
                "sync",
                commands,
                state,
                state,
                verification={"health_score": 0},
            )
            self.assertNotEqual(first.receipt_id, second.receipt_id)


if __name__ == "__main__":
    unittest.main()
