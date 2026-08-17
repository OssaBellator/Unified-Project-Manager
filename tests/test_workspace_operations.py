from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.workspace_operations import WorkspaceOperationError, plan_node_workspace_operations


class WorkspaceOperationTests(unittest.TestCase):
    def test_npm_workspace_sync_collapses_root_and_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "name": "root",
                "private": True,
                "packageManager": "npm@11",
                "workspaces": ["packages/*"],
            }), encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")

            plans, consumed = plan_node_workspace_operations(discover(root), "sync")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].argv, ("npm", "ci"))
            self.assertEqual(plans[0].workspace_root_component, ".:node")
            self.assertEqual(plans[0].member_components, ("packages/app:node",))
            self.assertEqual(consumed, {".:node", "packages/app:node"})

    def test_standalone_node_component_is_not_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11","workspaces":["packages/*"]}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            other = root / "tools" / "standalone"
            member.mkdir(parents=True); other.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            (other / "package.json").write_text('{"name":"standalone","packageManager":"npm@11"}', encoding="utf-8")
            (other / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

            _plans, consumed = plan_node_workspace_operations(discover(root), "install")
            self.assertNotIn("tools/standalone:node", consumed)

    def test_member_manager_conflict_blocks_workspace_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11","workspaces":["packages/*"]}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app","packageManager":"yarn@4"}', encoding="utf-8")
            (member / "yarn.lock").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(WorkspaceOperationError, "not workspace manager"):
                plan_node_workspace_operations(discover(root), "install")

    def test_yarn_workspace_sync_uses_declared_major_semantics(self) -> None:
        for declared, flag in (("yarn@1.22.22", "--frozen-lockfile"), ("yarn@4.9.2", "--immutable")):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "package.json").write_text(json.dumps({
                    "name": "root",
                    "private": True,
                    "packageManager": declared,
                    "workspaces": ["packages/*"],
                }), encoding="utf-8")
                (root / "yarn.lock").write_text("", encoding="utf-8")
                member = root / "packages" / "app"
                member.mkdir(parents=True)
                (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
                plans, consumed = plan_node_workspace_operations(discover(root), "sync")
                self.assertEqual(plans[0].argv, ("yarn", "install", flag))
                self.assertEqual(consumed, {".:node", "packages/app:node"})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"root","private":true,"workspaces":["packages/*"]}', encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceOperationError, "declared yarn major version"):
                plan_node_workspace_operations(discover(root), "sync")

    def test_pnpm_package_json_workspaces_are_not_assumed_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10","workspaces":["packages/*"]}', encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            plans, consumed = plan_node_workspace_operations(discover(root), "install")
            self.assertEqual(plans, [])
            self.assertEqual(consumed, set())

    def test_sync_requires_workspace_root_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11","workspaces":["packages/*"]}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceOperationError, "no native lockfile"):
                plan_node_workspace_operations(discover(root), "sync")


if __name__ == "__main__":
    unittest.main()
