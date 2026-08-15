from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import execute_python_lock_graph, plan_python_lock_graphs
from unified_project_manager.python_lock_reachability import analyze_python_lock_reachability


class PythonLockReachabilityTests(unittest.TestCase):
    def test_poetry_marker_path_is_conditional_not_unconditional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
conditional = {version = ">=2", markers = "python_version >= '3.12'"}

[[package]]
name = "conditional"
version = "2.0.0"
''', encoding="utf-8")
            graph = discover(root)
            result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

            report = analyze_python_lock_reachability(result, "conditional")

            self.assertEqual(len(report.packages), 1)
            package = report.packages[0]
            self.assertFalse(package.unconditional)
            self.assertEqual(
                package.paths[0].nodes,
                ("project:.:python", "parent@1.0.0", "conditional@2.0.0"),
            )
            self.assertEqual(package.paths[0].markers, ("python_version >= '3.12'",))
            self.assertTrue(package.paths[0].conditional)

    def test_pdm_marker_path_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent"]
[tool.pdm]
''', encoding="utf-8")
            (root / "pdm.lock").write_text('''
[metadata]
lock_version = "4.5.0"

[[package]]
name = "parent"
version = "1.0.0"
dependencies = ["conditional>=2; sys_platform == 'linux'"]

[[package]]
name = "conditional"
version = "2.0.0"
''', encoding="utf-8")
            graph = discover(root)
            result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

            report = analyze_python_lock_reachability(result, "conditional")

            self.assertFalse(report.packages[0].unconditional)
            self.assertEqual(report.packages[0].paths[0].markers, ("sys_platform == 'linux'",))

    def test_unconditional_and_conditional_routes_are_both_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["a", "b"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "a"
version = "1.0.0"
[package.dependencies]
target = "*"

[[package]]
name = "b"
version = "1.0.0"
[package.dependencies]
target = {version = "*", markers = "python_version < '4'"}

[[package]]
name = "target"
version = "5.0.0"
''', encoding="utf-8")
            graph = discover(root)
            result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

            report = analyze_python_lock_reachability(result, "target")

            self.assertTrue(report.packages[0].unconditional)
            paths = report.packages[0].paths
            self.assertEqual(len(paths), 2)
            self.assertFalse(paths[0].conditional)
            self.assertTrue(paths[1].conditional)

    def test_reachable_ambiguous_reference_is_reported_without_fake_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
shared = ">=1"

[[package]]
name = "shared"
version = "1.0.0"

[[package]]
name = "shared"
version = "2.0.0"
''', encoding="utf-8")
            graph = discover(root)
            result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

            report = analyze_python_lock_reachability(result, "shared")

            self.assertEqual(report.packages, ())
            self.assertEqual(len(report.ambiguities), 1)
            ambiguity = report.ambiguities[0]
            self.assertEqual(ambiguity.source, "parent@1.0.0")
            self.assertEqual(len(ambiguity.candidate_ids), 2)


if __name__ == "__main__":
    unittest.main()
