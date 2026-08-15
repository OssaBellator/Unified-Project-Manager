from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.native_graph import (
    execute_native_graph,
    parse_go_requirement_edges,
    parse_go_selected_modules,
    plan_native_graph,
    query_native_why,
    selected_inventory,
)


_SELECTED = '''
{"Path":"example.com/app","Main":true,"Dir":"/src/app","GoMod":"/src/app/go.mod","GoVersion":"1.24"}
{"Path":"example.com/a","Version":"v1.2.0","Dir":"/cache/a"}
{"Path":"example.com/b","Version":"v1.4.0","Dir":"/cache/b"}
{"Path":"example.com/old","Version":"v1.0.0","Replace":{"Path":"example.com/new","Version":"v1.1.0","Dir":"/cache/new"}}
{"Path":"example.com/local","Version":"v0.9.0","Replace":{"Path":"../local","Dir":"/src/local"}}
'''

_GRAPH = '''
example.com/app example.com/a@v1.2.0
example.com/app example.com/b@v1.3.0
example.com/a@v1.2.0 example.com/b@v1.4.0
example.com/a@v1.1.0 example.com/b@v1.2.0
'''


class NativeGraphTests(unittest.TestCase):
    def test_selected_modules_keep_replacement_semantics(self) -> None:
        modules = parse_go_selected_modules(_SELECTED, ".:go")
        by_name = {module.name: module for module in modules}
        self.assertTrue(by_name["example.com/app"].main)
        self.assertEqual(by_name["example.com/old"].effective_name, "example.com/new")
        self.assertEqual(by_name["example.com/old"].effective_version, "v1.1.0")
        self.assertTrue(by_name["example.com/local"].is_local_replacement)
        self.assertIsNone(by_name["example.com/local"].effective_version)

    def test_requirement_edges_distinguish_required_from_selected_version(self) -> None:
        modules = parse_go_selected_modules(_SELECTED, ".:go")
        edges = parse_go_requirement_edges(_GRAPH, ".:go", modules)
        root_to_b = next(edge for edge in edges if edge.source_name == "example.com/app" and edge.target_name == "example.com/b")
        self.assertEqual(root_to_b.required_version, "v1.3.0")
        self.assertEqual(root_to_b.selected_version, "v1.4.0")
        old_source = next(edge for edge in edges if edge.source_version == "v1.1.0")
        self.assertFalse(old_source.source_selected)

    def test_plan_uses_readonly_selected_build_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            plans, skips = plan_native_graph(discover(root))
            self.assertEqual(skips, [])
            self.assertEqual(plans[0].selected_argv, ("go", "list", "-mod=readonly", "-m", "-json", "all"))
            self.assertEqual(plans[0].edges_argv, ("go", "mod", "graph"))

    def test_execute_uses_exact_resolved_go_binary_and_collects_both_views(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            plan = plan_native_graph(discover(root))[0][0]
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                if "list" in argv:
                    return subprocess.CompletedProcess(argv, 0, _SELECTED, "")
                return subprocess.CompletedProcess(argv, 0, _GRAPH, "")

            result = execute_native_graph(plan, run=run, which=lambda _name: "/toolchains/go")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0], "/toolchains/go")
            self.assertEqual(calls[1][0], "/toolchains/go")
            self.assertEqual(len(selected_inventory([result])), 4)
            self.assertGreater(len(result.edges), 0)

    def test_native_why_uses_go_mod_why_module_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "# example.com/a\nexample.com/app/pkg\nexample.com/a/pkg\n",
                    "",
                )

            results, skips = query_native_why(discover(root), "example.com/a", run=run, which=lambda _name: "/toolchains/go")
            self.assertEqual(skips, [])
            self.assertTrue(results[0].needed)
            self.assertEqual(results[0].path, ("example.com/app/pkg", "example.com/a/pkg"))
            self.assertEqual(calls[0], ["/toolchains/go", "mod", "why", "-m", "example.com/a"])


class NativeSbomTests(unittest.TestCase):
    def test_native_go_sbom_uses_selected_versions_and_versionless_local_replacement(self) -> None:
        from unified_project_manager.native_graph import NativeGraphPlan, NativeGraphResult
        from unified_project_manager.sbom import cyclonedx_bom_with_native

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            graph = discover(root)
            modules = parse_go_selected_modules(_SELECTED, ".:go")
            edges = parse_go_requirement_edges(_GRAPH, ".:go", modules)
            plan = NativeGraphPlan(".:go", "go", "go", root, ("go",), ("go",))
            bom = cyclonedx_bom_with_native(graph, [NativeGraphResult(plan, modules, edges, 0)])
            refs = {item["bom-ref"]: item for item in bom["components"]}
            self.assertIn("pkg:golang/example.com%2Fa@v1.2.0", refs)
            self.assertIn("pkg:golang/example.com%2Fnew@v1.1.0", refs)
            local = next(item for item in bom["components"] if item["name"] == "example.com/local")
            self.assertNotIn("version", local)
            self.assertNotIn("purl", local)
            self.assertTrue(local["bom-ref"].startswith("urn:upm:go-local:sha256:"))


if __name__ == "__main__":
    unittest.main()
