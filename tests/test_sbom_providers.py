from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cargo_graph import CargoGraphPlan, CargoGraphResult, parse_cargo_metadata
from unified_project_manager.discovery import discover
from unified_project_manager.npm_graph import NpmGraphPlan, NpmGraphResult, parse_npm_ls
from unified_project_manager.sbom_providers import cyclonedx_bom_with_providers


class NativeSbomProviderTests(unittest.TestCase):
    def test_npm_provider_adds_logical_edges_only_for_static_purl_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"name":"app","version":"1.0.0","packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "app", "version": "1.0.0"},
                    "node_modules/a": {"version": "1.0.0"},
                    "node_modules/a/node_modules/b": {"version": "2.0.0"},
                },
            }), encoding="utf-8")
            tree = json.dumps({
                "name": "app", "version": "1.0.0",
                "dependencies": {"a": {"version": "1.0.0", "dependencies": {"b": {"version": "2.0.0"}}}},
            })
            root_name, root_version, packages, edges, problems = parse_npm_ls(tree, ".:node")
            result = NpmGraphResult(NpmGraphPlan(".:node", root), packages, edges, 0, root_name, root_version, problems)

            bom = cyclonedx_bom_with_providers(discover(root), npm_results=[result])
            dependencies = {item["ref"]: item["dependsOn"] for item in bom.get("dependencies", [])}
            self.assertEqual(dependencies["pkg:npm/a@1.0.0"], ["pkg:npm/b@2.0.0"])
            a = next(item for item in bom["components"] if item.get("purl") == "pkg:npm/a@1.0.0")
            properties = {(item["name"], item["value"]) for item in a["properties"]}
            self.assertIn(("upm:npm:identity-kind", "package-lock+logical-tree"), properties)

    def test_cargo_provider_adds_registry_relationships_without_relabeling_workspace_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('''version = 4
[[package]]
name="app"
version="0.1.0"
[[package]]
name="a"
version="1.0.0"
source="registry+https://github.com/rust-lang/crates.io-index"
[[package]]
name="b"
version="2.0.0"
source="registry+https://github.com/rust-lang/crates.io-index"
''', encoding="utf-8")
            metadata = json.dumps({
                "packages": [
                    {"name":"app","version":"0.1.0","id":"path+app#0.1.0","source":None,"manifest_path":str(root / "Cargo.toml")},
                    {"name":"a","version":"1.0.0","id":"registry+a#1.0.0","source":"registry+https://github.com/rust-lang/crates.io-index","manifest_path":"/cache/a/Cargo.toml"},
                    {"name":"b","version":"2.0.0","id":"registry+b#2.0.0","source":"registry+https://github.com/rust-lang/crates.io-index","manifest_path":"/cache/b/Cargo.toml"},
                ],
                "workspace_members":["path+app#0.1.0"],
                "workspace_default_members":["path+app#0.1.0"],
                "workspace_root":str(root),
                "resolve": {"root":"path+app#0.1.0","nodes":[
                    {"id":"path+app#0.1.0","deps":[{"name":"a","pkg":"registry+a#1.0.0","dep_kinds":[{"kind":None,"target":None}]}]},
                    {"id":"registry+a#1.0.0","deps":[{"name":"b","pkg":"registry+b#2.0.0","dep_kinds":[{"kind":None,"target":None}]}]},
                    {"id":"registry+b#2.0.0","deps":[]},
                ]},
            })
            packages, edges, resolve_root, workspace_root = parse_cargo_metadata(metadata, ".:rust")
            result = CargoGraphResult(CargoGraphPlan(".:rust", root), packages, edges, 0, resolve_root, workspace_root)

            bom = cyclonedx_bom_with_providers(discover(root), cargo_results=[result])
            dependencies = {item["ref"]: item["dependsOn"] for item in bom.get("dependencies", [])}
            self.assertEqual(dependencies["pkg:cargo/a@1.0.0"], ["pkg:cargo/b@2.0.0"])
            app = next(item for item in bom["components"] if item["name"] == "app")
            self.assertNotIn("purl", app)
            a = next(item for item in bom["components"] if item.get("purl") == "pkg:cargo/a@1.0.0")
            self.assertIn(
                {"name": "upm:cargo:identity-kind", "value": "cargo-lock+offline-metadata"},
                a["properties"],
            )


if __name__ == "__main__":
    unittest.main()
