from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.pnpm_graph import PnpmGraphPlan, PnpmGraphResult, parse_pnpm_list
from unified_project_manager.root_entrypoint import main


class PnpmProviderEntrypointTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        (root / "package.json").write_text(
            '{"name":"root","version":"1.0.0","private":true,"packageManager":"pnpm@11"}',
            encoding="utf-8",
        )
        (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        member = root / "packages" / "app"
        member.mkdir(parents=True)
        (member / "package.json").write_text('{"name":"app","version":"0.1.0"}', encoding="utf-8")
        return member

    def _native_result(self, root: Path) -> PnpmGraphResult:
        text = json.dumps([
            {
                "name": "root",
                "version": "1.0.0",
                "path": str(root),
                "private": True,
                "dependencies": {
                    "parent": {
                        "from": "parent",
                        "version": "1.0.0",
                        "dependencies": {
                            "child": {"from": "child", "version": "2.0.0", "deduped": True}
                        },
                    }
                },
            },
            {
                "name": "app",
                "version": "0.1.0",
                "path": str(root / "packages" / "app"),
                "private": False,
                "dependencies": {"child": {"from": "child", "version": "2.0.0"}},
            },
        ])
        projects, packages, edges = parse_pnpm_list(text, ".:node", root)
        return PnpmGraphResult(PnpmGraphPlan(".:node", root, recursive=True), projects, packages, edges, 0)

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_graph_preview_promotes_member_to_workspace_root_lock_only_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)

            code, data = self._json([
                "graph", str(root), "--native", "--component", "app", "--preview", "--json"
            ])

            self.assertEqual(code, 0)
            plan = next(item for item in data["plans"] if item["provider"] == "pnpm-lock-tree")
            self.assertEqual(plan["component"], ".:node")
            self.assertTrue(plan["recursive"])
            self.assertFalse(plan["network"])
            self.assertIn("--lockfile-only", plan["commands"][0])
            self.assertIn("Infinity", plan["commands"][0])

    def test_impact_and_why_preserve_workspace_project_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._workspace(root)
            result = self._native_result(root)

            with patch(
                "unified_project_manager.impact_provider_entrypoint.execute_pnpm_graph",
                return_value=result,
            ):
                impact_code, impact = self._json(["impact", "child", str(root), "--native", "--json"])
            with patch(
                "unified_project_manager.why_provider_entrypoint.execute_pnpm_graph",
                return_value=result,
            ):
                why_code, why = self._json(["why", "child", str(root), "--native", "--json"])

            self.assertEqual(impact_code, 0)
            self.assertEqual(why_code, 0)
            pnpm_impacts = [item for item in impact["impacts"] if item["provider"] == "pnpm-lock-tree"]
            self.assertEqual({item["workspace_project"] for item in pnpm_impacts}, {".", "packages/app"})
            self.assertNotIn("project", pnpm_impacts[0])
            pnpm_answers = [item for item in why["answers"] if item["provider"] == "pnpm-lock-tree"]
            self.assertEqual({item["workspace_project"] for item in pnpm_answers}, {".", "packages/app"})
            self.assertTrue(all(item["scope"] == "logical-dependency-tree" for item in pnpm_answers))


if __name__ == "__main__":
    unittest.main()
