from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.uv_graph import execute_uv_graph, parse_uv_lock, plan_uv_graphs
from unified_project_manager.uv_impact import analyze_uv_impact


_LOCK = '''
version = 1
requires-python = ">=3.12"

[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [
  { name = "foo", version = "1.0.0", marker = "sys_platform == 'linux'" },
  { name = "bar" },
]

[[package]]
name = "bar"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
  { name = "foo" },
]

[[package]]
name = "foo"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "foo"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
'''


class UvGraphTests(unittest.TestCase):
    def test_parser_preserves_markers_and_refuses_ambiguous_name_only_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = parse_uv_lock(_LOCK, ".:python", root / "uv.lock")
            self.assertTrue(result.succeeded)
            app = next(package for package in result.packages if package.name == "app")
            self.assertTrue(app.project_member)
            app_foo = next(edge for edge in result.edges if edge.source_id == app.package_id and edge.dependency_name == "foo")
            self.assertEqual(app_foo.requested_version, "1.0.0")
            self.assertEqual(app_foo.marker, "sys_platform == 'linux'")
            self.assertFalse(app_foo.ambiguous)
            bar = next(package for package in result.packages if package.name == "bar")
            bar_foo = next(edge for edge in result.edges if edge.source_id == bar.package_id and edge.dependency_name == "foo")
            self.assertTrue(bar_foo.ambiguous)
            self.assertIsNone(bar_foo.target_id)
            self.assertEqual(len(bar_foo.candidate_ids), 2)

    def test_plan_and_execute_are_static_and_network_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname="app"\nversion="0.1.0"\n[tool.uv]\n', encoding="utf-8")
            (root / "uv.lock").write_text(_LOCK, encoding="utf-8")
            plans = plan_uv_graphs(discover(root))
            self.assertEqual(len(plans), 1)
            self.assertFalse(plans[0].to_dict(root)["network"])
            self.assertFalse(plans[0].to_dict(root)["execution"])
            result = execute_uv_graph(plans[0])
            self.assertTrue(result.succeeded)
            self.assertGreater(len(result.packages), 0)

    def test_impact_uses_only_unambiguous_edges_and_reports_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = parse_uv_lock(_LOCK, ".:python", root / "uv.lock")
            impacts = analyze_uv_impact(result, "foo")
            one = next(impact for impact in impacts if impact.version == "1.0.0")
            two = next(impact for impact in impacts if impact.version == "2.0.0")
            self.assertIn(("app@0.1.0", "foo@1.0.0"), one.project_paths)
            self.assertNotIn("bar@1.0.0", one.transitive_dependents)
            self.assertEqual(one.ambiguous_references, 1)
            self.assertEqual(two.ambiguous_references, 1)
            self.assertEqual(two.project_paths, ())


if __name__ == "__main__":
    unittest.main()
