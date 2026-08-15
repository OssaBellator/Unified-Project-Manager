from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.python_lock_graph import execute_python_lock_graph, plan_python_lock_graphs
from unified_project_manager.python_lock_sbom import merge_python_lock_cyclonedx, merge_python_lock_spdx
from unified_project_manager.sbom import cyclonedx_bom
from unified_project_manager.spdx import spdx_document


class PythonLockSbomTests(unittest.TestCase):
    def _poetry_result(self, root: Path):
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
conditional = {version = ">=3", markers = "python_version >= '3.12'"}
localpkg = "*"

[[package]]
name = "child"
version = "2.0.0"

[[package]]
name = "conditional"
version = "3.0.0"

[[package]]
name = "localpkg"
version = "4.0.0"
[package.source]
type = "git"
url = "https://example.invalid/repo.git"

[[package]]
name = "orphan"
version = "9.9.9"
''', encoding="utf-8")
        graph = discover(root)
        return graph, execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])

    def test_cyclonedx_uses_reachable_registry_packages_and_omits_marker_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._poetry_result(root)
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])

            purls = {item.get("purl") for item in document.get("components", []) if item.get("purl")}
            self.assertIn("pkg:pypi/parent@1.0.0", purls)
            self.assertIn("pkg:pypi/child@2.0.0", purls)
            self.assertIn("pkg:pypi/conditional@3.0.0", purls)
            self.assertNotIn("pkg:pypi/localpkg@4.0.0", purls)
            self.assertNotIn("pkg:pypi/orphan@9.9.9", purls)

            dependencies = {
                item["ref"]: set(item.get("dependsOn", []))
                for item in document.get("dependencies", [])
            }
            self.assertEqual(
                dependencies["pkg:pypi/parent@1.0.0"],
                {"pkg:pypi/child@2.0.0"},
            )
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")
            self.assertIn(
                {"name":"upm:poetry:conditional-edges-omitted","value":"1"},
                parent.get("properties", []),
            )

    def test_spdx_uses_same_registry_and_unconditional_edge_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._poetry_result(root)
            document = merge_python_lock_spdx(
                spdx_document(graph, created=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                [result],
            )
            purls = {
                ref["referenceLocator"]
                for package in document.get("packages", [])
                for ref in package.get("externalRefs", [])
                if ref.get("referenceType") == "purl"
            }
            self.assertIn("pkg:pypi/parent@1.0.0", purls)
            self.assertIn("pkg:pypi/child@2.0.0", purls)
            self.assertNotIn("pkg:pypi/localpkg@4.0.0", purls)
            self.assertNotIn("pkg:pypi/orphan@9.9.9", purls)
            self.assertFalse(any(
                relation["relationshipType"] == "DEPENDS_ON"
                and relation["relatedSpdxElement"] == next(
                    package["SPDXID"] for package in document["packages"] if package["name"] == "conditional"
                )
                for relation in document["relationships"]
            ))


if __name__ == "__main__":
    unittest.main()
