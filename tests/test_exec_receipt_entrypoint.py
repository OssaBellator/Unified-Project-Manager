from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.native_exec import NativeExecResult
from unified_project_manager.root_entrypoint import main


class ExecReceiptEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
        )

    def test_preview_does_not_create_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["exec", "--path", str(root), "--json", "--", "view", "foo"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertFalse((root / ".upm" / "receipts").exists())

    def test_apply_records_partial_state_and_redacts_sensitive_args(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)

            def fake_execute(plan, _root, verify=False):
                self.assertFalse(verify)
                (root / "package.json").write_text(
                    '{"packageManager":"npm@11","changed":true}', encoding="utf-8"
                )
                return NativeExecResult(plan, 3, stderr="failed after change\n")

            output = io.StringIO()
            with patch(
                "unified_project_manager.exec_receipt_entrypoint.execute_native_exec",
                side_effect=fake_execute,
            ), redirect_stdout(output):
                code = main([
                    "exec", "--path", str(root), "--apply", "--no-verify", "--json",
                    "--", "config", "set", "--token", "secret-value",
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 3)
            self.assertFalse(data["receipt"]["succeeded"])
            command = data["receipt"]["commands"][0]
            self.assertNotIn("secret-value", command["argv"])
            self.assertIn("<redacted>", command["argv"])
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package.json"], "changed")
            self.assertTrue(Path(data["receipt_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
