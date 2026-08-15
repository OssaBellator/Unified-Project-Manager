from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import execute_python_lock_graph, plan_python_lock_graphs
from unified_project_manager.python_lock_reachability import analyze_python_lock_reachability


class PythonLockDirectConditionTests(unittest.TestCase):
    def _write_lock(self, root: Path, name: str = "child", version: str = "2.0.0") -> None:
        (root / "poetry.lock").write_text(f'''
[[package]]
name = "{name}"
version = "{version}"
''', encoding="utf-8")

    def _report(self, root: Path, package: str):
        graph = discover(root)
        plan = plan_python_lock_graphs(graph)[0]
        result = execute_python_lock_graph(graph, plan)
        self.assertTrue(result.succeeded)
        return graph, result, analyze_python_lock_reachability(result, package)

    def test_pep621_optional_group_is_conditional_at_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
[project.optional-dependencies]
docs = ["child>=2"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            self._write_lock(root)

            graph, result, report = self._report(root, "child")

            dependency = next(item for item in graph.components[0].dependencies if item.name == "child")
            self.assertEqual(dependency.scope, "optional:docs")
            root_edge = next(edge for edge in result.edges if edge.source_id.startswith("project:"))
            self.assertTrue(root_edge.optional)
            self.assertFalse(report.packages[0].unconditional)
            self.assertEqual(report.packages[0].paths[0].optional_edges, 1)

    def test_poetry_optional_dependency_table_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[tool.poetry]
name = "app"
version = "0.1.0"
[tool.poetry.dependencies]
python = ">=3.11"
child = { version = "^2", optional = true }
''', encoding="utf-8")
            self._write_lock(root)

            graph, result, report = self._report(root, "child")

            dependency = next(item for item in graph.components[0].dependencies if item.name == "child")
            self.assertEqual(dependency.scope, "optional:poetry")
            self.assertEqual(dependency.requirement, "^2")
            root_edge = next(edge for edge in result.edges if edge.source_id.startswith("project:"))
            self.assertTrue(root_edge.optional)
            self.assertFalse(report.packages[0].unconditional)

    def test_poetry_direct_marker_table_is_preserved_as_conditional_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[tool.poetry]
name = "app"
version = "0.1.0"
[tool.poetry.dependencies]
python = ">=3.11"
child = { version = "^2", markers = "sys_platform == 'linux'" }
''', encoding="utf-8")
            self._write_lock(root)

            graph, result, report = self._report(root, "child")

            dependency = next(item for item in graph.components[0].dependencies if item.name == "child")
            self.assertEqual(dependency.requirement, "^2; sys_platform == 'linux'")
            root_edge = next(edge for edge in result.edges if edge.source_id.startswith("project:"))
            self.assertFalse(root_edge.optional)
            self.assertEqual(root_edge.requirement, "^2; sys_platform == 'linux'")
            self.assertFalse(report.packages[0].unconditional)
            self.assertEqual(report.packages[0].paths[0].markers, ("sys_platform == 'linux'",))

    def test_optional_poetry_group_marks_group_dependencies_conditional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[tool.poetry]
name = "app"
version = "0.1.0"
[tool.poetry.group.docs]
optional = true
[tool.poetry.group.docs.dependencies]
child = "^2"
''', encoding="utf-8")
            self._write_lock(root)

            graph, result, report = self._report(root, "child")

            dependency = next(item for item in graph.components[0].dependencies if item.name == "child")
            self.assertEqual(dependency.scope, "optional:development:docs")
            root_edge = next(edge for edge in result.edges if edge.source_id.startswith("project:"))
            self.assertTrue(root_edge.optional)
            self.assertFalse(report.packages[0].unconditional)


if __name__ == "__main__":
    unittest.main()
