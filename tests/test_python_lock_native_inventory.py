from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import PythonLockGraphPlan, PythonLockGraphResult
from unified_project_manager.python_lock_native_inventory import (
    PythonLockNativeInventoryError,
    assemble_python_lock_native_inventory,
    build_python_lock_native_inventory,
)


class PythonLockNativeInventoryTests(unittest.TestCase):
    def test_exact_bom_retains_graph_evidence_and_excludes_orphan_static_seed(self) -> None:
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
child = ">=2"

[[package]]
name = "child"
version = "2.0.0"

[[package]]
name = "orphan"
version = "9.9.9"
''', encoding="utf-8")
            graph = discover(root)

            inventory = build_python_lock_native_inventory(graph)

            self.assertTrue(inventory.applicable)
            self.assertEqual(inventory.provider_counts(), {"poetry-lock": 1, "pdm-lock": 0})
            self.assertEqual(len(inventory.plans), 1)
            self.assertEqual(len(inventory.results), 1)
            self.assertTrue(inventory.results[0].succeeded)
            purls = {
                component.get("purl")
                for component in inventory.bom.get("components", [])
                if component.get("purl")
            }
            self.assertEqual(purls, {
                "pkg:pypi/parent@1.0.0",
                "pkg:pypi/child@2.0.0",
            })
            self.assertNotIn("pkg:pypi/orphan@9.9.9", purls)

    def test_invalid_structured_lock_fails_before_bom_is_exposed(self) -> None:
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

            with self.assertRaises(PythonLockNativeInventoryError) as raised:
                build_python_lock_native_inventory(graph)

            self.assertIn("pdm-lock .:python", str(raised.exception))
            self.assertIn("record-level", str(raised.exception))

    def test_assembly_rejects_results_that_do_not_match_planned_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname="app"\nversion="0.1.0"\n', encoding="utf-8")
            graph = discover(root)
            expected = PythonLockGraphPlan(".:python", "poetry", root / "poetry.lock")
            other = PythonLockGraphPlan(".:python", "pdm", root / "pdm.lock")
            result = PythonLockGraphResult(other, [], [], ())

            with self.assertRaises(PythonLockNativeInventoryError) as raised:
                assemble_python_lock_native_inventory(graph, [expected], [result])

            self.assertIn("do not match the planned provider order", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
