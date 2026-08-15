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
from unified_project_manager.npm_graph import (
    NpmGraphPlan,
    NpmGraphResult,
    execute_npm_graph,
    npm_provider_component_keys,
    parse_npm_ls,
    plan_npm_graphs,
)
from unified_project_manager.npm_impact import analyze_npm_impact


_NPM_LS = json.dumps({
    "name": "app",
    "version": "1.0.0",
    "dependencies": {
        "a": {
            "version": "1.0.0",
            "overridden": False,
            "dependencies": {"c": {"version": "1.0.0", "overridden": False}},
        },
        "b": {
            "version": "1.0.0",
            "overridden": False,
            "dependencies": {"c": {"version": "2.0.0", "overridden": False}},
        },
    },
})


def _result(root: Path) -> NpmGraphResult:
    root_name, root_version, packages, edges, problems = parse_npm_ls(_NPM_LS, ".:node")
    return NpmGraphResult(
        NpmGraphPlan(".:node", root),
        packages,
        edges,
        0,
        root_name=root_name,
        root_version=root_version,
        problems=problems,
    )


class NpmGraphTests(unittest.TestCase):
    def test_parser_preserves_duplicate_logical_occurrences(self) -> None:
        root_name, root_version, packages, edges, problems = parse_npm_ls(_NPM_LS, ".:node")
        self.assertEqual((root_name, root_version), ("app", "1.0.0"))
        c_packages = [item for item in packages if item.name == "c"]
        self.assertEqual({item.version for item in c_packages}, {"1.0.0", "2.0.0"})
        self.assertEqual(len({item.ref for item in c_packages}), 2)
        self.assertEqual(len(edges), len(packages))
        self.assertEqual(problems, ())

    def test_plan_requires_authoritative_npm_lock_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            plans = plan_npm_graphs(discover(root))
            self.assertEqual(plans[0].argv, ("npm", "ls", "--all", "--json", "--package-lock-only"))

    def test_workspace_member_selector_promotes_to_root_lock_with_exact_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "name": "root", "private": True, "packageManager": "npm@11", "workspaces": ["packages/*"]
            }), encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app","version":"1.0.0"}', encoding="utf-8")
            graph = discover(root)

            plans = plan_npm_graphs(graph, selector="app")

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:node")
            self.assertEqual(plans[0].cwd, root)
            self.assertEqual(plans[0].workspace_selector, "./packages/app")
            self.assertEqual(plans[0].argv[-2:], ("--workspace", "./packages/app"))
            self.assertEqual(npm_provider_component_keys(graph), {".:node", "packages/app:node"})

    def test_workspace_root_is_planned_once_for_unscoped_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({
                "name": "root", "private": True, "packageManager": "npm@11", "workspaces": ["packages/*"]
            }), encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            member = root / "packages" / "app"
            member.mkdir(parents=True)
            (member / "package.json").write_text('{"name":"app","packageManager":"npm@11"}', encoding="utf-8")
            (member / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

            plans = plan_npm_graphs(discover(root))

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].cwd, root)
            self.assertIsNone(plans[0].workspace_selector)

    def test_execute_uses_exact_resolved_npm_and_no_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = NpmGraphPlan(".:node", root)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, _NPM_LS, "")

            result = execute_npm_graph(plan, run=run, which=lambda _name: "/tools/npm")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/tools/npm", "ls", "--all", "--json", "--package-lock-only"])
            self.assertFalse((root / "node_modules").exists())
            self.assertEqual(len(result.packages), 4)

    def test_multi_provider_graph_json_includes_npm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            result = _result(root)
            output = io.StringIO()
            with patch("unified_project_manager.graph_entrypoint.execute_npm_graph", return_value=result), redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["results"][0]["provider"], "npm-lock-tree")
            self.assertEqual(data["results"][0]["root"]["name"], "app")
            self.assertEqual(len(data["results"][0]["packages"]), 4)

    def test_npm_impact_preserves_each_occurrence_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impacts = analyze_npm_impact(_result(Path(temporary)), "c")
            self.assertEqual(len(impacts), 2)
            paths = {impact.root_path for impact in impacts}
            self.assertIn(("app@1.0.0", "a@1.0.0", "c@1.0.0"), paths)
            self.assertIn(("app@1.0.0", "b@1.0.0", "c@2.0.0"), paths)
            self.assertEqual({impact.direct_parent for impact in impacts}, {"a@1.0.0", "b@1.0.0"})

    def test_public_npm_impact_json_labels_logical_tree_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            output = io.StringIO()
            with patch("unified_project_manager.impact_provider_entrypoint.execute_npm_graph", return_value=_result(root)), redirect_stdout(output):
                code = main(["impact", "c", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual({item["provider"] for item in data["impacts"]}, {"npm-lock-tree"})
            self.assertEqual({item["scope"] for item in data["impacts"]}, {"logical-dependency-tree"})
            self.assertEqual(len(data["impacts"]), 2)


if __name__ == "__main__":
    unittest.main()
