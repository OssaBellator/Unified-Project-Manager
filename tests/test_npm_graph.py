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
    parse_npm_ls,
    plan_npm_graphs,
)


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
            plan = NpmGraphPlan(".:node", root)
            result = NpmGraphResult(
                plan,
                parse_npm_ls(_NPM_LS, ".:node")[2],
                parse_npm_ls(_NPM_LS, ".:node")[3],
                0,
                root_name="app",
                root_version="1.0.0",
            )
            output = io.StringIO()
            with patch("unified_project_manager.graph_entrypoint.execute_npm_graph", return_value=result), redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["results"][0]["provider"], "npm-lock-tree")
            self.assertEqual(data["results"][0]["root"]["name"], "app")
            self.assertEqual(len(data["results"][0]["packages"]), 4)


if __name__ == "__main__":
    unittest.main()
