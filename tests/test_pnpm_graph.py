from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.pnpm_graph import (
    PnpmGraphPlan,
    execute_pnpm_graph,
    parse_pnpm_list,
    plan_pnpm_graphs,
)
from unified_project_manager.pnpm_impact import analyze_pnpm_impact


class PnpmGraphTests(unittest.TestCase):
    def _output(self, root: Path) -> str:
        return json.dumps([
            {
                "name": "root",
                "version": "1.0.0",
                "path": str(root),
                "private": True,
                "dependencies": {
                    "alias-a": {
                        "from": "actual-a",
                        "version": "1.2.3",
                        "resolved": "https://registry.example/actual-a/-/actual-a-1.2.3.tgz",
                        "path": str(root / "node_modules" / ".pnpm" / "actual-a@1.2.3"),
                        "dependencies": {
                            "child": {
                                "from": "child",
                                "version": "2.0.0",
                                "deduped": True,
                                "dedupedDependenciesCount": 4,
                            }
                        },
                    }
                },
                "devDependencies": {
                    "dev-only": {"from": "dev-only", "version": "3.0.0"}
                },
            },
            {
                "name": "app",
                "version": "0.1.0",
                "path": str(root / "packages" / "app"),
                "private": False,
                "optionalDependencies": {
                    "child": {"from": "child", "version": "2.0.0"}
                },
            },
        ])

    def test_parser_preserves_projects_scopes_aliases_and_dedupe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects, packages, edges = parse_pnpm_list(self._output(root), ".:node", root)

            self.assertEqual([project.path for project in projects], [".", "packages/app"])
            alias = next(package for package in packages if package.alias == "alias-a")
            self.assertEqual(alias.name, "actual-a")
            self.assertEqual(alias.scope, "runtime")
            child = next(package for package in packages if package.depth == 2)
            self.assertTrue(child.deduped)
            self.assertEqual(child.deduped_dependencies_count, 4)
            dev = next(package for package in packages if package.name == "dev-only")
            self.assertEqual(dev.scope, "development")
            optional = [package for package in packages if package.scope == "optional"]
            self.assertEqual(len(optional), 1)
            self.assertTrue(any(edge.target_ref == child.ref for edge in edges))

    def test_impact_matches_actual_name_or_alias_and_keeps_workspace_root_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            projects, packages, edges = parse_pnpm_list(self._output(root), ".:node", root)
            from unified_project_manager.pnpm_graph import PnpmGraphResult

            result = PnpmGraphResult(PnpmGraphPlan(".:node", root, recursive=True), projects, packages, edges, 0)
            by_name = analyze_pnpm_impact(result, "actual-a")
            by_alias = analyze_pnpm_impact(result, "alias-a")
            child = analyze_pnpm_impact(result, "child")

            self.assertEqual(len(by_name), 1)
            self.assertEqual(by_name[0], by_alias[0])
            self.assertEqual(by_name[0].root_path, ("root@1.0.0", "actual-a@1.2.3"))
            self.assertEqual({impact.project for impact in child}, {".", "packages/app"})
            nested = next(impact for impact in child if impact.project == ".")
            self.assertEqual(nested.root_path, ("root@1.0.0", "actual-a@1.2.3", "child@2.0.0"))
            self.assertTrue(nested.deduped)

    def test_execute_uses_exact_resolved_binary_and_lockfile_only_depth_infinity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PnpmGraphPlan(".:node", root, recursive=True)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, self._output(root), "")

            result = execute_pnpm_graph(plan, run=run, which=lambda _name: "/tools/pnpm")

            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/tools/pnpm")
            self.assertIn("--lockfile-only", calls[0][0])
            self.assertIn("Infinity", calls[0][0])
            self.assertIn("-r", calls[0][0])

    def test_member_selector_promotes_to_pnpm_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(
                '{"name":"root","private":true,"packageManager":"pnpm@11"}', encoding="utf-8"
            )
            (root / "pnpm-workspace.yaml").write_text("packages:\n  - packages/*\n", encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app"}', encoding="utf-8")

            plans = plan_pnpm_graphs(discover(root), selector="app")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].cwd, root)
            self.assertTrue(plans[0].recursive)
            self.assertEqual(plans[0].component, ".:node")


if __name__ == "__main__":
    unittest.main()
