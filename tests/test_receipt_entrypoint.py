from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.models import CommandResult
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

    def test_receipts_report_current_then_drift_after_manual_native_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_execute(plan, _root, verify=False):
                (root / "package.json").write_text(
                    '{"name":"app","packageManager":"npm@11","dependencies":{"foo":"1.0.0"}}',
                    encoding="utf-8",
                )
                return CommandResult(plan, True, 0)

            with patch(
                "unified_project_manager.operation_receipt_entrypoint.execute_plan",
                side_effect=fake_execute,
            ):
                apply_code, applied = self._json([
                    "add", "foo", "--path", str(root), "--apply", "--no-verify", "--json"
                ])

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
