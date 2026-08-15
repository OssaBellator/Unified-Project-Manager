from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.cargo_graph import (
    CargoGraphPlan,
    CargoGraphResult,
    execute_cargo_graph,
    parse_cargo_metadata,
    plan_cargo_graphs,
)
from unified_project_manager.cargo_impact import analyze_cargo_impact
from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main


_METADATA = json.dumps({
    "packages": [
        {
            "name": "app", "version": "0.1.0", "id": "path+app#0.1.0",
            "source": None, "manifest_path": "/src/app/Cargo.toml",
        },
        {
            "name": "mid", "version": "1.0.0", "id": "registry+mid#1.0.0",
            "source": "registry+https://github.com/rust-lang/crates.io-index", "manifest_path": "/cargo/mid/Cargo.toml",
        },
        {
            "name": "leaf", "version": "1.0.0", "id": "registry+leaf#1.0.0",
            "source": "registry+https://github.com/rust-lang/crates.io-index", "manifest_path": "/cargo/leaf1/Cargo.toml",
        },
        {
            "name": "leaf", "version": "2.0.0", "id": "registry+leaf#2.0.0",
            "source": "registry+https://github.com/rust-lang/crates.io-index", "manifest_path": "/cargo/leaf2/Cargo.toml",
        },
    ],
    "workspace_members": ["path+app#0.1.0"],
    "workspace_default_members": ["path+app#0.1.0"],
    "workspace_root": "/src/app",
    "resolve": {
        "root": "path+app#0.1.0",
        "nodes": [
            {
                "id": "path+app#0.1.0",
                "deps": [
                    {"name": "mid", "pkg": "registry+mid#1.0.0", "dep_kinds": [{"kind": None, "target": None}]},
                    {"name": "leaf2", "pkg": "registry+leaf#2.0.0", "dep_kinds": [{"kind": "dev", "target": None}]},
                ],
            },
            {
                "id": "registry+mid#1.0.0",
                "deps": [
                    {"name": "leaf", "pkg": "registry+leaf#1.0.0", "dep_kinds": [{"kind": None, "target": "cfg(unix)"}]},
                ],
            },
            {"id": "registry+leaf#1.0.0", "deps": []},
            {"id": "registry+leaf#2.0.0", "deps": []},
        ],
    },
})


def _result(root: Path) -> CargoGraphResult:
    packages, edges, resolve_root, workspace_root = parse_cargo_metadata(_METADATA, ".:rust")
    return CargoGraphResult(
        CargoGraphPlan(".:rust", root),
        packages,
        edges,
        0,
        resolve_root=resolve_root,
        workspace_root=workspace_root,
    )


class CargoGraphTests(unittest.TestCase):
    def test_parser_preserves_package_ids_kinds_targets_and_workspace_members(self) -> None:
        packages, edges, resolve_root, workspace_root = parse_cargo_metadata(_METADATA, ".:rust")
        self.assertEqual(resolve_root, "path+app#0.1.0")
        self.assertEqual(workspace_root, "/src/app")
        app = next(package for package in packages if package.name == "app")
        self.assertTrue(app.workspace_member)
        self.assertTrue(app.workspace_default_member)
        leaf_versions = {package.version for package in packages if package.name == "leaf"}
        self.assertEqual(leaf_versions, {"1.0.0", "2.0.0"})
        unix_edge = next(edge for edge in edges if edge.target_id == "registry+leaf#1.0.0")
        self.assertEqual(unix_edge.kinds, ("normal",))
        self.assertEqual(unix_edge.targets, ("cfg(unix)",))
        dev_edge = next(edge for edge in edges if edge.target_id == "registry+leaf#2.0.0")
        self.assertEqual(dev_edge.kinds, ("dev",))

    def test_plan_is_locked_offline_and_workspace_root_owns_nested_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / "member"
            member.mkdir()
            (root / "Cargo.toml").write_text('[workspace]\nmembers=["member"]\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
            (member / "Cargo.toml").write_text('[package]\nname="member"\nversion="0.1.0"\n', encoding="utf-8")
            graph = discover(root)
            plans = plan_cargo_graphs(graph)
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].component, ".:rust")
            self.assertEqual(plans[0].argv, ("cargo", "metadata", "--format-version", "1", "--locked", "--offline"))

    def test_execute_uses_exact_cargo_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, _METADATA, "")

            result = execute_cargo_graph(CargoGraphPlan(".:rust", root), run=run, which=lambda _name: "/toolchains/cargo")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], ["/toolchains/cargo", "metadata", "--format-version", "1", "--locked", "--offline"])
            self.assertEqual(calls[0][1]["cwd"], root)

    def test_impact_preserves_multiple_versions_and_workspace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            impacts = analyze_cargo_impact(_result(Path(temporary)), "leaf")
            self.assertEqual({impact.version for impact in impacts}, {"1.0.0", "2.0.0"})
            one = next(impact for impact in impacts if impact.version == "1.0.0")
            two = next(impact for impact in impacts if impact.version == "2.0.0")
            self.assertIn(("app@0.1.0", "mid@1.0.0", "leaf@1.0.0"), one.workspace_paths)
            self.assertIn(("app@0.1.0", "leaf@2.0.0"), two.workspace_paths)

    def test_public_graph_and_impact_label_cargo_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
            result = _result(root)

            output = io.StringIO()
            with patch("unified_project_manager.graph_entrypoint.execute_cargo_graph", return_value=result), redirect_stdout(output):
                code = main(["graph", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(data["results"][0]["provider"], "cargo-metadata")
            self.assertFalse(data["results"][0]["plan"]["network"])

            output = io.StringIO()
            with patch("unified_project_manager.impact_provider_entrypoint.execute_cargo_graph", return_value=result), redirect_stdout(output):
                code = main(["impact", "leaf", str(root), "--native", "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual({item["provider"] for item in data["impacts"]}, {"cargo-metadata"})
            self.assertEqual({item["scope"] for item in data["impacts"]}, {"locked-offline-dependency-graph"})


if __name__ == "__main__":
    unittest.main()
