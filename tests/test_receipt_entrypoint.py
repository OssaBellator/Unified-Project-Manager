from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.models import CommandResult
from unified_project_manager.receipts import receipt_identity_digest, receipt_identity_payload
from unified_project_manager.root_entrypoint import main


class ReceiptEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"npm@11"}', encoding="utf-8"
        )
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{"name":"app"}}}', encoding="utf-8"
        )

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def _apply_add(self, root: Path, package: str, version: str) -> tuple[int, dict]:
        def fake_execute(plan, _root, verify=False):
            (root / "package.json").write_text(
                json.dumps({
                    "name": "app",
                    "packageManager": "npm@11",
                    "dependencies": {package: version},
                }),
                encoding="utf-8",
            )
            (root / "package-lock.json").write_text(
                json.dumps({
                    "lockfileVersion": 3,
                    "packages": {"": {"name": "app", "dependencies": {package: version}}},
                }),
                encoding="utf-8",
            )
            return CommandResult(plan, True, 0)

        with patch(
            "unified_project_manager.operation_receipt_entrypoint.execute_plan",
            side_effect=fake_execute,
        ):
            return self._json([
                "add", package, "--path", str(root), "--apply", "--no-verify", "--json"
            ])

    def test_receipts_report_current_then_drift_after_manual_native_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            apply_code, applied = self._apply_add(root, "foo", "1.0.0")

            current_code, current = self._json(["receipts", str(root), "--json"])
            self.assertEqual(apply_code, 0)
            self.assertTrue(Path(applied["receipt_path"]).is_file())
            self.assertEqual(current_code, 0)
            self.assertEqual(current["state"], "current")
            self.assertEqual(current["invalid_receipts"], 0)
            self.assertFalse(current["current_state_drift"])
            self.assertFalse(current["network_executed"])
            self.assertFalse(current["mutation_executed"])

            (root / "package.json").write_text(
                '{"name":"app","packageManager":"npm@11","dependencies":{"foo":"2.0.0"}}',
                encoding="utf-8",
            )
            drift_code, drift = self._json(["receipts", str(root), "--json"])

            self.assertEqual(drift_code, 1)
            self.assertEqual(drift["state"], "drifted")
            self.assertTrue(drift["current_state_drift"])
            changes = {item["path"]: item["status"] for item in drift["changes"]}
            self.assertEqual(changes["package.json"], "changed")

    def test_receipt_chain_is_preview_first_and_invalidated_by_new_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            first_code, _first = self._apply_add(root, "foo", "1.0.0")
            self.assertEqual(first_code, 0)

            preview_code, preview = self._json([
                "receipts", "chain", str(root), "--json"
            ])
            self.assertEqual(preview_code, 0)
            self.assertFalse(preview["executed"])
            self.assertFalse((root / ".upm" / "receipt-chain.json").exists())
            self.assertEqual(len(preview["proposed"]["entries"]), 1)
            self.assertEqual(len(preview["anchor_digest"]), 64)
            self.assertFalse(preview["authenticated"])

            anchor_code, anchored = self._json([
                "receipts", "chain", str(root), "--apply", "--json"
            ])
            self.assertEqual(anchor_code, 0)
            self.assertTrue(Path(anchored["path"]).is_file())
            self.assertTrue(anchored["validation"]["valid"])
            self.assertFalse(anchored["authenticated"])

            current_code, current = self._json(["receipts", str(root), "--json"])
            self.assertEqual(current_code, 0)
            self.assertTrue(current["receipt_chain"]["valid"])

            second_code, _second = self._apply_add(root, "bar", "2.0.0")
            self.assertEqual(second_code, 0)
            changed_code, changed = self._json(["receipts", str(root), "--json"])
            self.assertEqual(changed_code, 1)
            self.assertFalse(changed["receipt_chain"]["valid"])
            self.assertTrue(changed["receipt_chain"]["unexpected_receipts"])

            status_code, status = self._json(["status", str(root), "--json"])
            self.assertEqual(status_code, 1)
            self.assertIn("receipt-chain", status["summary"]["blockers"])
            self.assertEqual(status["local_evidence"]["summary"]["receipt_chain_state"], "invalid")

            reanchor_code, reanchored = self._json([
                "receipts", "chain", str(root), "--apply", "--json"
            ])
            self.assertEqual(reanchor_code, 0)
            self.assertTrue(reanchored["validation"]["valid"])
            self.assertEqual(len(reanchored["chain"]["entries"]), 2)

            clear_code, clear = self._json(["status", str(root), "--json"])
            self.assertEqual(clear_code, 0)
            self.assertNotIn("receipt-chain", clear["summary"]["blockers"])
            self.assertEqual(clear["local_evidence"]["summary"]["receipt_chain_state"], "valid")

    def test_receipt_chain_detects_different_valid_receipt_at_anchored_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            apply_code, applied = self._apply_add(root, "foo", "1.0.0")
            self.assertEqual(apply_code, 0)
            anchor_code, _anchored = self._json([
                "receipts", "chain", str(root), "--apply", "--json"
            ])
            self.assertEqual(anchor_code, 0)

            receipt_path = Path(applied["receipt_path"])
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            original_id = data["receipt_id"]
            data["operation"] = "rewritten-valid-receipt"
            data["receipt_id"] = receipt_identity_digest(receipt_identity_payload(
                version=data["version"],
                operation=data.get("operation"),
                commands=data.get("commands"),
                before=data.get("before"),
                after=data.get("after"),
                created_at=data.get("created_at"),
                verification=data.get("verification"),
            ))
            self.assertNotEqual(data["receipt_id"], original_id)
            receipt_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            code, status = self._json(["receipts", str(root), "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(status["invalid_receipts"], 0)
            self.assertFalse(status["receipt_chain"]["valid"])
            anchored_invalid = status["receipt_chain"]["invalid_receipts"]
            self.assertEqual(anchored_invalid, [receipt_path.relative_to(root).as_posix()])
            self.assertEqual(status["state"], "current")

    def test_receipts_absent_is_clean_non_mutating_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            code, data = self._json(["receipts", str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["state"], "absent")
            self.assertEqual(data["receipts"], 0)
            self.assertFalse((root / ".upm").exists())


if __name__ == "__main__":
    unittest.main()
