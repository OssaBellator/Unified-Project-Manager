from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.cargo_graph import CargoGraphPlan, CargoGraphResult, parse_cargo_metadata
from unified_project_manager.entrypoint import main
from unified_project_manager.npm_graph import NpmGraphPlan, NpmGraphResult, parse_npm_ls


class WhyProviderTests(unittest.TestCase):
    def test_npm_why_returns_each_logical_occurrence_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            tree = json.dumps({
                "name": "app", "version": "1.0.0",
                "dependencies": {
                    "a": {"version": "1.0.0", "dependencies": {"c": {"version": "1.0.0"}}},
                    "b": {"version": "1.0.0", "dependencies": {"c": {"version": "2.0.0"}}},
                },
            })
            root_name, root_version, packages, edges, problems = parse_npm_ls(tree, ".:node")
            result = NpmGraphResult(NpmGraphPlan(".:node", root), packages, edges, 0, root_name, root_version, problems)
            output = io.StringIO()
            with patch("unified_project_manager.why_provider_entrypoint.execute_npm_graph", return_value=result), redirect_stdout(output):
                code = main(["why", "c", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            answers = data["answers"]
            self.assertEqual(len(answers), 2)
            self.assertEqual({item["provider"] for item in answers}, {"npm-lock-tree"})
            self.assertEqual({item["scope"] for item in answers}, {"logical-dependency-tree"})
            self.assertEqual(
                {tuple(item["root_path"]) for item in answers},
                {
                    ("app@1.0.0", "a@1.0.0", "c@1.0.0"),
                    ("app@1.0.0", "b@1.0.0", "c@2.0.0"),
                },
            )

    def test_cargo_why_preserves_locked_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
            metadata = json.dumps({
                "packages": [
                    {"name":"app","version":"0.1.0","id":"path+app#0.1.0","source":None,"manifest_path":str(root / "Cargo.toml")},
                    {"name":"mid","version":"1.0.0","id":"registry+mid#1.0.0","source":"registry+x","manifest_path":"/cache/mid/Cargo.toml"},
                    {"name":"leaf","version":"2.0.0","id":"registry+leaf#2.0.0","source":"registry+x","manifest_path":"/cache/leaf/Cargo.toml"},
                ],
                "workspace_members":["path+app#0.1.0"],
                "workspace_default_members":["path+app#0.1.0"],
                "workspace_root":str(root),
                "resolve": {"root":"path+app#0.1.0","nodes":[
                    {"id":"path+app#0.1.0","deps":[{"name":"mid","pkg":"registry+mid#1.0.0","dep_kinds":[{"kind":None,"target":None}]}]},
                    {"id":"registry+mid#1.0.0","deps":[{"name":"leaf","pkg":"registry+leaf#2.0.0","dep_kinds":[{"kind":None,"target":None}]}]},
                    {"id":"registry+leaf#2.0.0","deps":[]},
                ]},
            })
            packages, edges, resolve_root, workspace_root = parse_cargo_metadata(metadata, ".:rust")
            result = CargoGraphResult(CargoGraphPlan(".:rust", root), packages, edges, 0, resolve_root, workspace_root)
            output = io.StringIO()
            with patch("unified_project_manager.why_provider_entrypoint.execute_cargo_graph", return_value=result), redirect_stdout(output):
                code = main(["why", "leaf", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            answer = data["answers"][0]
            self.assertEqual(answer["provider"], "cargo-metadata")
            self.assertEqual(answer["scope"], "locked-offline-dependency-graph")
            self.assertIn(["app@0.1.0", "mid@1.0.0", "leaf@2.0.0"], answer["workspace_paths"])


if __name__ == "__main__":
    unittest.main()
