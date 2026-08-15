from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.models import CommandPlan, CommandResult, DoctorReport, Finding
from unified_project_manager.root_entrypoint import main


class RepairReceiptEntrypointTests(unittest.TestCase):
    def test_applied_repair_persists_partial_native_state_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(
                '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
            )
            plan = CommandPlan("sync", ".:node", "npm", ("npm", "ci"), root)
            diagnosis = DoctorReport(root, [
                Finding(
                    "installed.version-mismatch",
                    "error",
                    "installed state differs",
                    ".:node",
                )
            ])

            def fake_execute(selected, _root, verify=False):
                (root / "package-lock.json").write_text(
                    '{"lockfileVersion":3,"packages":{"":{"repaired":true}}}', encoding="utf-8"
                )
                return CommandResult(selected, True, 0, stdout="repaired\n")

            output = io.StringIO()
            with patch(
                "unified_project_manager.repair_receipt_entrypoint.diagnose",
                return_value=diagnosis,
            ), patch(
                "unified_project_manager.repair_receipt_entrypoint.plan_repairs",
                return_value=[plan],
            ), patch(
                "unified_project_manager.repair_receipt_entrypoint.execute_plan",
                side_effect=fake_execute,
            ), redirect_stdout(output):
                code = main([
                    "repair", str(root), "--apply", "--no-verify", "--json"
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(Path(data["receipt_path"]).is_file())
            self.assertEqual(data["receipt"]["operation"], "repair")
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["package-lock.json"], "changed")


if __name__ == "__main__":
    unittest.main()
