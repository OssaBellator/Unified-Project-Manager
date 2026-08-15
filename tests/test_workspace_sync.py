from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.workspace_ops import (
    WorkspaceOperationError,
    WorkspaceSyncPlan,
    execute_workspace_sync,
    prepare_workspace_sync,
)


class WorkspaceSyncTests(unittest.TestCase):
    def test_preflight_discovers_external_members_and_blocks_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external_temp:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            (member / "go.mod").write_text("module example.com/member\ngo 1.24\n", encoding="utf-8")
            external = Path(external_temp)
            (external / "go.mod").write_text("module example.com/external\ngo 1.24\n", encoding="utf-8")
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            payload = json.dumps({
                "Use": [
                    {"DiskPath": "./member"},
                    {"DiskPath": str(external)},
                ]
            })

            def inspect_run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, payload, "")

            plan = prepare_workspace_sync(discover(root), run=inspect_run, which=lambda _name: "/tools/go")

            self.assertEqual(plan.external_members, (external,))
            self.assertIn(member / "go.mod", plan.tracked_files)
            with self.assertRaisesRegex(WorkspaceOperationError, "external"):
                execute_workspace_sync(plan, root, which=lambda _name: "/tools/go")

    def test_apply_reports_changed_files_and_uses_exact_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            go_mod = member / "go.mod"
            go_mod.write_text("module example.com/member\n", encoding="utf-8")
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            plan = WorkspaceSyncPlan(
                workspace=".:go-workspace",
                cwd=root,
                argv=("go", "work", "sync"),
                tracked_files=(root / "go.work", root / "go.work.sum", go_mod, member / "go.sum"),
                external_members=(),
            )
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                go_mod.write_text("module example.com/member\ngo 1.24\n", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "synced\n", "")

            result = execute_workspace_sync(plan, root, run=run, which=lambda _name: "/tools/go")

            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/tools/go", "work", "sync"])
            self.assertEqual(calls[0][1]["env"]["GOWORK"], str(root / "go.work"))
            self.assertEqual(result.changed_files, ("member/go.mod",))

    def test_cli_sync_is_preview_first_and_surfaces_external_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external_temp:
            root = Path(temporary)
            (root / "go.work").write_text("go 1.24\n", encoding="utf-8")
            external = Path(external_temp)
            plan = WorkspaceSyncPlan(
                workspace=".:go-workspace",
                cwd=root,
                argv=("go", "work", "sync"),
                tracked_files=(root / "go.work", external / "go.mod"),
                external_members=(external,),
            )
            output = io.StringIO()
            with patch("unified_project_manager.workspace_sync_entrypoint.prepare_workspace_sync", return_value=plan), redirect_stdout(output):
                code = main(["workspace", "sync", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertTrue(data["external_apply_blocked"])
            self.assertEqual(data["plan"]["argv"], ["go", "work", "sync"])


if __name__ == "__main__":
    unittest.main()
