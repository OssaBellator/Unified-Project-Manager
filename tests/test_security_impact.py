from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.cargo_graph import CargoGraphPlan, CargoGraphResult, parse_cargo_metadata
from unified_project_manager.native_graph import NativeGraphPlan, NativeGraphResult, NativeModule, NativeRequirementEdge
from unified_project_manager.npm_graph import NpmGraphPlan, NpmGraphResult, parse_npm_ls
from unified_project_manager.pnpm_graph import PnpmGraphPlan, PnpmGraphResult, parse_pnpm_list
from unified_project_manager.security_impact import correlate_advisory_impact
from unified_project_manager.uv_graph import parse_uv_lock


class SecurityImpactTests(unittest.TestCase):
    def test_npm_advisory_maps_to_each_matching_logical_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tree = json.dumps({
                "name":"app","version":"1.0.0","dependencies":{
                    "a":{"version":"1.0.0","dependencies":{"foo":{"version":"2.0.0"}}},
                    "b":{"version":"1.0.0","dependencies":{"foo":{"version":"2.0.0"}}},
                }
            })
            root_name, root_version, packages, edges, problems = parse_npm_ls(tree, ".:node")
            npm = NpmGraphResult(NpmGraphPlan(".:node", root), packages, edges, 0, root_name, root_version, problems)
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"2.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-foo"}],
            }]}]}
            impacts = correlate_advisory_impact(report, npm_results=[npm])
            self.assertEqual(len(impacts), 2)
            self.assertEqual({impact.advisory_id for impact in impacts}, {"GHSA-foo"})
            self.assertEqual(
                {impact.paths[0] for impact in impacts},
                {
                    ("app@1.0.0", "a@1.0.0", "foo@2.0.0"),
                    ("app@1.0.0", "b@1.0.0", "foo@2.0.0"),
                },
            )

    def test_pnpm_advisory_preserves_workspace_project_and_alias_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tree = json.dumps([{
                "name":"app","version":"1.0.0","path":str(root),
                "dependencies":{
                    "foo-alias":{
                        "from":"foo","version":"2.0.0","deduped":True,
                    }
                },
            }])
            projects, packages, edges = parse_pnpm_list(tree, ".:node", root)
            pnpm = PnpmGraphResult(PnpmGraphPlan(".:node", root), projects, packages, edges, 0)
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"2.0.0","ecosystem":"npm"},
                "vulnerabilities":[{"id":"GHSA-pnpm"}],
            }]}]}

            impact = correlate_advisory_impact(report, pnpm_results=[pnpm])[0]

            self.assertEqual(impact.provider, "pnpm-lock-tree")
            self.assertEqual(impact.paths, (("app@1.0.0", "foo@2.0.0"),))
            self.assertEqual(impact.evidence["alias"], "foo-alias")
            self.assertEqual(impact.evidence["workspace_project"], ".")
            self.assertTrue(impact.evidence["deduped"])

    def test_cargo_advisory_keeps_crate_version_and_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = json.dumps({
                "packages":[
                    {"name":"app","version":"0.1.0","id":"path+app#0.1.0","source":None,"manifest_path":"/src/app/Cargo.toml"},
                    {"name":"foo","version":"1.2.3","id":"registry+foo#1.2.3","source":"registry+x","manifest_path":"/cache/foo/Cargo.toml"},
                ],
                "workspace_members":["path+app#0.1.0"],
                "workspace_default_members":["path+app#0.1.0"],
                "workspace_root":"/src/app",
                "resolve":{"root":"path+app#0.1.0","nodes":[
                    {"id":"path+app#0.1.0","deps":[{"name":"foo","pkg":"registry+foo#1.2.3","dep_kinds":[{"kind":None,"target":None}]}]},
                    {"id":"registry+foo#1.2.3","deps":[]},
                ]},
            })
            packages, edges, resolve_root, workspace_root = parse_cargo_metadata(metadata, ".:rust")
            cargo = CargoGraphResult(CargoGraphPlan(".:rust", root), packages, edges, 0, resolve_root, workspace_root)
            report = {"results":[{"packages":[{
                "package":{"name":"foo","version":"1.2.3","ecosystem":"crates.io"},
                "vulnerabilities":[{"id":"RUSTSEC-TEST"}],
            }]}]}
            impact = correlate_advisory_impact(report, cargo_results=[cargo])[0]
            self.assertEqual(impact.provider, "cargo-metadata")
            self.assertEqual(impact.paths, (("app@0.1.0", "foo@1.2.3"),))

    def test_go_advisory_maps_to_module_requirement_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = NativeGraphPlan(".:go", "go", "go", root, ("go",), ("go",))
            go = NativeGraphResult(plan, [
                NativeModule(".:go", "example.com/app", None, main=True),
                NativeModule(".:go", "example.com/foo", "v1.2.3"),
            ], [
                NativeRequirementEdge(".:go", "example.com/app", None, "example.com/foo", "v1.2.3", "v1.2.3", True),
            ], 0)
            report = {"results":[{"packages":[{
                "package":{"name":"example.com/foo","version":"v1.2.3","ecosystem":"Go"},
                "vulnerabilities":[{"id":"GO-TEST"}],
            }]}]}
            impact = correlate_advisory_impact(report, go_results=[go])[0]
            self.assertEqual(impact.provider, "go-modules")
            self.assertIn(("example.com/app", "example.com/foo"), impact.paths)

    def test_uv_advisory_uses_normalized_python_name_and_reports_ambiguous_refs(self) -> None:
        lock = '''
version = 1
[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "my-package", version = "2.0.0" }]
[[package]]
name = "my-package"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            uv = parse_uv_lock(lock, ".:python", root / "uv.lock")
            report = {"results":[{"packages":[{
                "package":{"name":"My_Package","version":"2.0.0","ecosystem":"PyPI"},
                "vulnerabilities":[{"id":"PYSEC-TEST"}],
            }]}]}
            impact = correlate_advisory_impact(report, uv_results=[uv])[0]
            self.assertEqual(impact.provider, "uv-lock")
            self.assertEqual(impact.paths, (("app@0.1.0", "my-package@2.0.0"),))


if __name__ == "__main__":
    unittest.main()
