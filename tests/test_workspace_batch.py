from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.pnpm_workspace import PnpmWorkspaceMember, PnpmWorkspaceResult, plan_pnpm_workspace
from unified_project_manager.workspace_batch import (
    WorkspaceBatchError,
    WorkspaceInspectionRequired,
    plan_workspace_batch,
    required_pnpm_workspace_inspections,
)


class WorkspaceBatchTests(unittest.TestCase):
    def test_package_json_workspace_collapses_and_leaves_other_ecosystems_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "packageManager": "npm@11", "workspaces": ["packages/*"]
            }), encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            rust = root / "engine"
            rust.mkdir()
            (rust / "Cargo.toml").write_text('[package]\nname="engine"\nversion="0.1.0"\n', encoding="utf-8")
            (rust / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")

            result = plan_workspace_batch(discover(root), "sync")

            self.assertEqual(len(result.workspace_plans), 1)
            self.assertEqual(result.workspace_plans[0].argv, ("npm", "ci"))
            self.assertEqual(set(result.consumed_components), {".:node", "packages/app:node"})
            self.assertEqual(result.standalone_components, ("engine:rust",))

    def test_pnpm_requires_explicit_native_inspection_before_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")

            graph = discover(root)
            with self.assertRaises(WorkspaceInspectionRequired) as raised:
                plan_workspace_batch(graph, "install")
            self.assertEqual(raised.exception.roots, (root,))
            self.assertEqual(required_pnpm_workspace_inspections(graph)[0].root, root)

    def test_successful_pnpm_inspection_collapses_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"root","packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            graph = discover(root)
            plan = plan_pnpm_workspace(root)
            assert plan is not None
            inspection = PnpmWorkspaceResult(plan, [
                PnpmWorkspaceMember(root, "root", None, None),
                PnpmWorkspaceMember(member, "app", None, None),
            ], 0)

            result = plan_workspace_batch(graph, "sync", pnpm_results=[inspection])

            self.assertEqual(len(result.workspace_plans), 1)
            workspace = result.workspace_plans[0]
            self.assertEqual(workspace.workspace_kind, "pnpm")
            self.assertEqual(workspace.argv, ("pnpm", "install", "--frozen-lockfile"))
            self.assertEqual(set(result.consumed_components), {".:node", "packages/app:node"})
            self.assertEqual(result.standalone_components, ())

    def test_failed_pnpm_inspection_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            graph = discover(root)
            plan = plan_pnpm_workspace(root)
            assert plan is not None
            failed = PnpmWorkspaceResult(plan, [], 1, stderr="bad workspace")
            with self.assertRaisesRegex(WorkspaceBatchError, "bad workspace"):
                plan_workspace_batch(graph, "install", pnpm_results=[failed])

    def test_pnpm_external_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            outside = Path(temporary) / "outside"
            root.mkdir(); outside.mkdir()
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            (outside / "package.json").write_text('{"name":"outside"}', encoding="utf-8")
            graph = discover(root)
            plan = plan_pnpm_workspace(root)
            assert plan is not None
            inspection = PnpmWorkspaceResult(plan, [PnpmWorkspaceMember(outside, "outside", None, None)], 0)
            with self.assertRaisesRegex(WorkspaceBatchError, "outside"):
                plan_workspace_batch(graph, "install", pnpm_results=[inspection])


if __name__ == "__main__":
    unittest.main()
