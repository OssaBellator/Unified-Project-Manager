from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.entrypoint import main
from unified_project_manager.workspace_ops import WorkspaceSyncPlan, WorkspaceSyncResult


class WorkspaceSyncReceiptTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        member = root / "member"
        member.mkdir()
        (root / "go.work").write_text("go 1.24\nuse ./member\n", encoding="utf-8")
        (member / "go.mod").write_text("module example.com/member\ngo 1.24\n", encoding="utf-8")
        return member

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_internal_workspace_sync_writes_complete_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = self._project(root)
            plan = WorkspaceSyncPlan(
                workspace=".:go-workspace",
                cwd=root,
                argv=("go", "work", "sync"),
                tracked_files=(root / "go.work", member / "go.mod"),
                external_members=(),
            )

            def fake_execute(selected, _root, allow_external=False):
                self.assertFalse(allow_external)
                (member / "go.mod").write_text(
                    "module example.com/member\ngo 1.24\nrequire example.com/a v1.0.0\n",
                    encoding="utf-8",
                )
                return WorkspaceSyncResult(
                    selected,
                    True,
                    0,
                    changed_files=("member/go.mod",),
                )

            with patch(
                "unified_project_manager.workspace_sync_entrypoint.prepare_workspace_sync",
                return_value=plan,
            ), patch(
                "unified_project_manager.workspace_sync_entrypoint.execute_workspace_sync",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    "workspace", "sync", str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertEqual(data["receipt_scope"], "project-complete")
            self.assertIsNone(data["receipt_reason"])
            self.assertTrue(Path(data["receipt_path"]).is_file())
            self.assertEqual(data["receipt"]["operation"], "workspace-sync")
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["member/go.mod"], "changed")

    def test_failed_internal_sync_still_records_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = self._project(root)
            plan = WorkspaceSyncPlan(
                workspace=".:go-workspace",
                cwd=root,
                argv=("go", "work", "sync"),
                tracked_files=(root / "go.work", member / "go.mod"),
                external_members=(),
            )

            def fake_execute(selected, _root, allow_external=False):
                (member / "go.mod").write_text(
                    "module example.com/member\ngo 1.24\n// partial\n",
                    encoding="utf-8",
                )
                return WorkspaceSyncResult(selected, True, 2, changed_files=("member/go.mod",), stderr="failed\n")

            with patch(
                "unified_project_manager.workspace_sync_entrypoint.prepare_workspace_sync",
                return_value=plan,
            ), patch(
                "unified_project_manager.workspace_sync_entrypoint.execute_workspace_sync",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    "workspace", "sync", str(root), "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 2)
            self.assertFalse(data["receipt"]["succeeded"])
            self.assertEqual(data["receipt"]["commands"][0]["returncode"], 2)
            changes = {item["path"]: item["status"] for item in data["receipt"]["changes"]}
            self.assertEqual(changes["member/go.mod"], "changed")

    def test_external_workspace_sync_never_writes_incomplete_project_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external_temporary:
            root = Path(temporary)
            member = self._project(root)
            external = Path(external_temporary)
            (external / "go.mod").write_text("module example.com/external\ngo 1.24\n", encoding="utf-8")
            plan = WorkspaceSyncPlan(
                workspace=".:go-workspace",
                cwd=root,
                argv=("go", "work", "sync"),
                tracked_files=(root / "go.work", member / "go.mod", external / "go.mod"),
                external_members=(external,),
            )

            def fake_execute(selected, _root, allow_external=False):
                self.assertTrue(allow_external)
                (external / "go.mod").write_text(
                    "module example.com/external\ngo 1.24\n// changed externally\n",
                    encoding="utf-8",
                )
                return WorkspaceSyncResult(
                    selected,
                    True,
                    0,
                    changed_files=(str(external / "go.mod"),),
                )

            with patch(
                "unified_project_manager.workspace_sync_entrypoint.prepare_workspace_sync",
                return_value=plan,
            ), patch(
                "unified_project_manager.workspace_sync_entrypoint.execute_workspace_sync",
                side_effect=fake_execute,
            ):
                code, data = self._json([
                    "workspace", "sync", str(root), "--allow-external", "--apply", "--no-verify", "--json"
                ])

            self.assertEqual(code, 0)
            self.assertIsNone(data["receipt"])
            self.assertIsNone(data["receipt_path"])
            self.assertEqual(data["receipt_scope"], "external-unrepresented")
            self.assertIn("outside the project root", data["receipt_reason"])
            self.assertFalse((root / ".upm" / "receipts").exists())


if __name__ == "__main__":
    unittest.main()
