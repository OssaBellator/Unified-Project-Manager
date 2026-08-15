from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import (
    analyze_python_lock_impact,
    execute_python_lock_graph,
    plan_python_lock_graphs,
)


class PythonLockGraphTests(unittest.TestCase):
    def test_poetry_lock_relationships_produce_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["requests>=2"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "requests"
version = "2.32.0"
groups = ["main"]
[package.dependencies]
urllib3 = ">=1.21.1,<3"

[[package]]
name = "urllib3"
version = "2.2.1"
groups = ["main"]

[metadata]
lock-version = "2.1"
''', encoding="utf-8")
            graph = discover(root)
            plan = plan_python_lock_graphs(graph)[0]

            result = execute_python_lock_graph(graph, plan)
            impacts = analyze_python_lock_impact(result, "urllib3")

            self.assertTrue(result.succeeded)
            self.assertEqual(plan.manager, "poetry")
            self.assertEqual(len(impacts), 1)
            self.assertEqual(
                impacts[0].project_paths,
                (("project:.:python", "requests@2.32.0", "urllib3@2.2.1"),),
            )
            self.assertEqual(impacts[0].ambiguous_references, 0)

    def test_pdm_lock_pep508_dependencies_preserve_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["requests>=2"]
[tool.pdm]
''', encoding="utf-8")
            (root / "pdm.lock").write_text('''
[metadata]
lock_version = "4.5.0"

[[package]]
name = "requests"
version = "2.32.0"
groups = ["default"]
dependencies = [
  "urllib3>=2; python_version >= '3.9'",
]

[[package]]
name = "urllib3"
version = "2.2.1"
groups = ["default"]
''', encoding="utf-8")
            graph = discover(root)
            plan = plan_python_lock_graphs(graph)[0]
            result = execute_python_lock_graph(graph, plan)

            self.assertTrue(result.succeeded)
            self.assertEqual(plan.manager, "pdm")
            edge = next(edge for edge in result.edges if edge.source_id.startswith("requests@"))
            self.assertEqual(edge.dependency_name, "urllib3")
            self.assertEqual(edge.requirement, ">=2")
            self.assertEqual(edge.marker, "python_version >= '3.9'")
            self.assertFalse(edge.ambiguous)
            self.assertEqual(
                analyze_python_lock_impact(result, "urllib3")[0].project_paths,
                (("project:.:python", "requests@2.32.0", "urllib3@2.2.1"),),
            )

    def test_duplicate_locked_name_remains_ambiguous_and_is_not_guessed(self) -> None:
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

            edge = next(edge for edge in result.edges if edge.source_id.startswith("parent@"))
            self.assertTrue(edge.ambiguous)
            self.assertIsNone(edge.target_id)
            self.assertEqual(len(edge.candidate_ids), 2)
            self.assertEqual(analyze_python_lock_impact(result, "shared"), [])

    def test_git_or_path_source_is_retained_as_non_registry_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["localpkg"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "localpkg"
version = "1.0.0"
[package.source]
type = "git"
url = "https://example.invalid/repo.git"
reference = "main"
resolved_reference = "abc"
''', encoding="utf-8")
            graph = discover(root)
            result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

            self.assertEqual(result.packages[0].source_kind, "git")
            self.assertEqual(len(analyze_python_lock_impact(result, "localpkg")), 1)


if __name__ == "__main__":
    unittest.main()
