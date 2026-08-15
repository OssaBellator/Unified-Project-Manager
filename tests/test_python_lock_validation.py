from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import plan_python_lock_graphs
from unified_project_manager.python_lock_validation import (
    execute_validated_python_lock_graph,
    validate_python_lock_plan,
)


class PythonLockValidationTests(unittest.TestCase):
    def test_poetry_contract_reports_format_and_accepts_structured_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
            (root / "poetry.lock").write_text('''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
child = {version = ">=2", markers = "python_version >= '3.10'"}

[[package]]
name = "child"
version = "2.0.0"

[metadata]
lock-version = "2.1"
''', encoding="utf-8")
            graph = discover(root)
            plan = plan_python_lock_graphs(graph)[0]

            contract = validate_python_lock_plan(plan)

            self.assertEqual(contract.manager, "poetry")
            self.assertEqual(contract.format_version, "2.1")
            self.assertEqual(contract.packages, 2)
            self.assertTrue(execute_validated_python_lock_graph(graph, plan).succeeded)

    def test_pdm_contract_retains_lock_strategy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
[tool.pdm]
''', encoding="utf-8")
            (root / "pdm.lock").write_text('''
[metadata]
lock_version = "4.5.0"
strategy = ["cross_platform", "inherit_metadata"]

[[package]]
name = "parent"
version = "1.0.0"
dependencies = ["child>=2"]

[[package]]
name = "child"
version = "2.0.0"
''', encoding="utf-8")
            plan = plan_python_lock_graphs(discover(root))[0]

            contract = validate_python_lock_plan(plan)

            self.assertEqual(contract.format_version, "4.5.0")
            self.assertEqual(contract.strategies, ("cross_platform", "inherit_metadata"))

    def test_record_level_marker_is_rejected_until_modeled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
[tool.pdm]
''', encoding="utf-8")
            (root / "pdm.lock").write_text('''
[metadata]
lock_version = "4.5.0"

[[package]]
name = "conditional"
version = "2.0.0"
marker = "python_version >= '3.12'"
''', encoding="utf-8")
            graph = discover(root)
            plan = plan_python_lock_graphs(graph)[0]

            result = execute_validated_python_lock_graph(graph, plan)

            self.assertFalse(result.succeeded)
            self.assertIn("record-level", result.error)
            self.assertIn("marker", result.error)

    def test_unexpected_dependency_shape_is_rejected_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
[tool.pdm]
''', encoding="utf-8")
            (root / "pdm.lock").write_text('''
[metadata]
lock_version = "4.5.0"

[[package]]
name = "parent"
version = "1.0.0"
dependencies = { child = ">=2" }
''', encoding="utf-8")
            graph = discover(root)
            plan = plan_python_lock_graphs(graph)[0]

            result = execute_validated_python_lock_graph(graph, plan)

            self.assertFalse(result.succeeded)
            self.assertIn("list of PEP-508 strings", result.error)


if __name__ == "__main__":
    unittest.main()
