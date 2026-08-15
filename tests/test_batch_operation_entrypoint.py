from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.pnpm_workspace import PnpmWorkspaceMember, PnpmWorkspaceResult, plan_pnpm_workspace
from unified_project_manager.root_entrypoint import main


class BatchOperationEntrypointTests(unittest.TestCase):
    def _npm_workspace(self, root: Path) -> None:
        (root / "package.json").write_text(json.dumps({
            "name": "root",
            "packageManager": "npm@11",
            "workspaces": ["packages/*"],
        }), encoding="utf-8")
        (root / "package-lock.json").write_text(
            '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
        )
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")

    def test_sync_all_collapses_package_json_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_workspace(root)
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["sync", "--all", "--path", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(len(data["plans"]), 1)
            self.assertEqual(data["plans"][0]["component"], ".:node")
            self.assertEqual(data["plans"][0]["argv"], ["npm", "ci"])
            self.assertEqual(
                set(data["workspace_batch"]["consumed_components"]),
                {".:node", "packages/app:node"},
            )
            self.assertEqual(data["workspace_batch"]["standalone_components"], [])

    def test_sync_all_keeps_non_workspace_components_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_workspace(root)
            rust = root / "engine"
            rust.mkdir()
            (rust / "Cargo.toml").write_text(
                '[package]\nname="engine"\nversion="0.1.0"\n', encoding="utf-8"
            )
            (rust / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                code = main(["sync", "--all", "--path", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            commands = {tuple(plan["argv"]) for plan in data["plans"]}
            self.assertEqual(commands, {("npm", "ci"), ("cargo", "fetch", "--locked")})
            self.assertEqual(data["workspace_batch"]["standalone_components"], ["engine:rust"])

    def test_pnpm_workspace_is_inspected_non_mutating_before_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(
                '{"name":"root","packageManager":"pnpm@10"}', encoding="utf-8"
            )
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")
            inspection_plan = plan_pnpm_workspace(root)
            assert inspection_plan is not None
            inspection = PnpmWorkspaceResult(
                inspection_plan,
                [
                    PnpmWorkspaceMember(root, "root", None, None),
                    PnpmWorkspaceMember(member, "app", None, None),
                ],
                0,
            )
            output = io.StringIO()

            with patch(
                "unified_project_manager.batch_operation_entrypoint.execute_pnpm_workspace",
                return_value=inspection,
            ), redirect_stdout(output):
                code = main(["install", "--all", "--path", str(root), "--json"])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["executed"])
            self.assertEqual(data["plans"][0]["argv"], ["pnpm", "install"])
            self.assertEqual(len(data["workspace_inspections"]), 1)
            self.assertFalse(data["workspace_inspections"][0]["plan"]["network"])
            self.assertFalse(data["workspace_inspections"][0]["plan"]["mutates_project"])

    def test_all_rejects_component_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(
                '{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8"
            )
            output = io.StringIO()

            with redirect_stdout(output):
                code = main([
                    "install", "--all", "--component", ".:node",
                    "--path", str(root), "--json",
                ])

            data = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertIn("--all cannot be combined", data["error"])


if __name__ == "__main__":
    unittest.main()
