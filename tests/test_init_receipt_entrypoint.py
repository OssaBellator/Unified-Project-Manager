from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.models import CommandResult
from unified_project_manager.root_entrypoint import main


class InitReceiptEntrypointTests(unittest.TestCase):
    def test_applied_init_records_new_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = Path.cwd()
            os.chdir(root)
            try:
                def fake_execute(plan, _root, verify=False):
                    plan.cwd.mkdir(parents=True, exist_ok=True)
                    (plan.cwd / "package.json").write_text(
                        '{"name":"app","packageManager":"npm@11"}', encoding="utf-8"
                    )
                    return CommandResult(plan, True, 0, stdout="created\n")

                output = io.StringIO()
                with patch(
                    "unified_project_manager.init_receipt_entrypoint.execute_initialization",
                    side_effect=fake_execute,
                ), redirect_stdout(output):
                    code = main([
                        "init", "app", "--ecosystem", "node", "--manager", "npm",
                        "--apply", "--no-verify", "--json",
                    ])
            finally:
                os.chdir(previous)

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["receipt"]["operation"], "init")
            self.assertTrue(Path(data["receipt_path"]).is_file())
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["app/package.json"], "added")

    def test_go_init_preview_uses_explicit_module_and_writes_no_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = Path.cwd()
            os.chdir(root)
            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main([
                        "init", "service", "--ecosystem", "go",
                        "--module", "example.com/service", "--json",
                    ])
            finally:
                os.chdir(previous)

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(data["plan"]["argv"], ["go", "mod", "init", "example.com/service"])
            self.assertFalse((root / ".upm" / "receipts").exists())


if __name__ == "__main__":
    unittest.main()
