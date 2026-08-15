from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.pnpm_workspace import (
    execute_pnpm_workspace,
    find_pnpm_workspace_root,
    parse_pnpm_workspace_list,
    plan_pnpm_workspace,
)


class PnpmWorkspaceTests(unittest.TestCase):
    def test_finds_workspace_root_without_parsing_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            self.assertEqual(find_pnpm_workspace_root(member, root), root)
            plan = plan_pnpm_workspace(member, root)
            assert plan is not None
            self.assertEqual(plan.argv, ("pnpm", "list", "-r", "--depth", "-1", "--json"))
            self.assertFalse(plan.to_dict()["mutates_project"])

    def test_parses_workspace_project_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = json.dumps([
                {"name": "root", "version": "1.0.0", "path": str(root), "private": True},
                {"name": "app", "version": "2.0.0", "path": str(root / "packages" / "app")},
            ])
            members = parse_pnpm_workspace_list(data, root)
            self.assertEqual({member.name for member in members}, {"root", "app"})
            app = next(member for member in members if member.name == "app")
            self.assertEqual(app.to_dict(root)["path"], "packages/app")

    def test_execute_uses_exact_resolved_pnpm_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            plan = plan_pnpm_workspace(root)
            assert plan is not None
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, json.dumps([{"name": "root", "path": str(root)}]), "")

            result = execute_pnpm_workspace(plan, run=run, which=lambda _name: "/tools/pnpm")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/tools/pnpm", "list", "-r", "--depth", "-1", "--json"])
            self.assertEqual(calls[0][1]["cwd"], root)

    def test_invalid_json_is_explicit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            plan = plan_pnpm_workspace(root)
            assert plan is not None
            result = execute_pnpm_workspace(
                plan,
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "not-json", ""),
                which=lambda _name: "/tools/pnpm",
            )
            self.assertFalse(result.succeeded)
            self.assertIn("Could not parse", result.stderr)


if __name__ == "__main__":
    unittest.main()
