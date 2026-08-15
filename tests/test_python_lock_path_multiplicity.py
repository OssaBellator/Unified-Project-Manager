from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import execute_python_lock_graph, plan_python_lock_graphs
from unified_project_manager.python_lock_reachability import analyze_python_lock_reachability


class PythonLockPathMultiplicityTests(unittest.TestCase):
    def _result(self, root: Path):
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
shared = "2.0.0"

[[package]]
name = "b"
version = "1.0.0"
[package.dependencies]
shared = "2.0.0"

[[package]]
name = "shared"
version = "2.0.0"
''', encoding="utf-8")
        graph = discover(root)
        return execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

    def test_distinct_same_condition_paths_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_python_lock_reachability(self._result(Path(temporary)), "shared")
            package = report.packages[0]

            self.assertEqual(
                {path.nodes for path in package.paths},
                {
                    ("project:.:python", "a@1.0.0", "shared@2.0.0"),
                    ("project:.:python", "b@1.0.0", "shared@2.0.0"),
                },
            )
            self.assertTrue(package.unconditional)
            self.assertFalse(package.paths_truncated)

    def test_path_budget_sets_explicit_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_python_lock_reachability(
                self._result(Path(temporary)),
                "shared",
                max_paths_per_package=1,
            )
            package = report.packages[0]

            self.assertEqual(len(package.paths), 1)
            self.assertTrue(package.paths_truncated)

    def test_search_state_budget_also_sets_explicit_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = analyze_python_lock_reachability(
                self._result(Path(temporary)),
                "shared",
                max_paths_per_package=64,
                max_search_states=2,
            )

            # A tiny state budget can truncate before reaching a target. The
            # provider must not manufacture a complete-looking path set.
            if report.packages:
                self.assertTrue(report.packages[0].paths_truncated)
            else:
                self.assertEqual(report.ambiguities, ())


if __name__ == "__main__":
    unittest.main()
