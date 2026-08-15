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


class OperationReceiptEntrypointTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text(
            '{"name":"app","packageManager":"npm@11"}', encoding="utf-8"
        )
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
        )

    def test_preview_does_not_create_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["add", "react", "--path", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertFalse((root / ".upm" / "receipts").exists())

    def test_apply_writes_receipt_and_records_changed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            def fake_execute(plan, _root, verify=False):
                self.assertFalse(verify)
                (root / "package.json").write_text(
                    '{"name":"app","packageManager":"npm@11","dependencies":{"react":"19.0.0"}}',
                    encoding="utf-8",
                )
                return CommandResult(plan=plan, executed=True, returncode=0, stdout="added\n")

            output = io.StringIO()
            with patch(
                "unified_project_manager.operation_receipt_entrypoint.execute_plan",
                side_effect=fake_execute,
            ), redirect_stdout(output):
                code = main([
                    "add", "react", "--path", str(root), "--apply", "--no-verify", "--json"
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(data["executed"])
            self.assertTrue(Path(data["receipt_path"]).is_file())
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package.json"], "changed")
            self.assertEqual(data["receipt"]["commands"][0]["argv"], ["npm", "install", "react"])

    def test_failed_apply_still_persists_partial_state_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)

            def fake_execute(plan, _root, verify=False):
                (root / "package-lock.json").write_text(
                    '{"lockfileVersion":3,"packages":{"":{"partial":true}}}', encoding="utf-8"
                )
                return CommandResult(plan=plan, executed=True, returncode=2, stderr="native failure\n")

            output = io.StringIO()
            with patch(
                "unified_project_manager.operation_receipt_entrypoint.execute_plan",
                side_effect=fake_execute,
            ), redirect_stdout(output):
                code = main([
                    "sync", "--path", str(root), "--apply", "--no-verify", "--json"
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertFalse(data["receipt"]["succeeded"])
            self.assertTrue(Path(data["receipt_path"]).is_file())
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package-lock.json"], "changed")
            self.assertEqual(data["receipt"]["commands"][0]["returncode"], 2)


if __name__ == "__main__":
    unittest.main()
