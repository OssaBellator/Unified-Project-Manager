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


class PythonLockSbomUncertaintyTests(unittest.TestCase):
    def _project(self, root: Path, lock: str, dependency: str = "parent") -> tuple[object, object]:
        (root / "pyproject.toml").write_text(f'''
[project]
name = "app"
version = "0.1.0"
dependencies = ["{dependency}"]
[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
        (root / "poetry.lock").write_text(lock, encoding="utf-8")
        graph = discover(root)
        result = execute_python_lock_graph(graph, plan_python_lock_graphs(graph)[0])
        return graph, result

    def test_ambiguous_candidates_remain_scan_visible_but_not_related_unconditionally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
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
''')
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])
            purls = {item.get("purl") for item in document["components"] if item.get("purl")}

            self.assertEqual(purls, {
                "pkg:pypi/parent@1.0.0",
                "pkg:pypi/shared@1.0.0",
                "pkg:pypi/shared@2.0.0",
            })
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")
            self.assertIn(
                {"name":"upm:poetry:ambiguous-edges-omitted","value":"1"},
                parent.get("properties", []),
            )
            for version in ("1.0.0", "2.0.0"):
                shared = next(item for item in document["components"] if item.get("purl") == f"pkg:pypi/shared@{version}")
                self.assertIn(
                    {"name":"upm:poetry:ambiguous-reachability","value":"true"},
                    shared.get("properties", []),
                )
                self.assertIn(
                    {"name":"upm:poetry:reachability","value":"possible"},
                    shared.get("properties", []),
                )
            self.assertFalse(any(
                item["ref"] == "pkg:pypi/parent@1.0.0"
                and any(target.startswith("pkg:pypi/shared@") for target in item.get("dependsOn", []))
                for item in document.get("dependencies", [])
            ))

    def test_optional_edge_is_conditional_not_unconditional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
optional-child = {version = "2.0.0", optional = true}

[[package]]
name = "optional-child"
version = "2.0.0"
''')
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")
            child = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/optional-child@2.0.0")

            self.assertIn(
                {"name":"upm:poetry:conditional-edges-omitted","value":"1"},
                parent.get("properties", []),
            )
            self.assertIn(
                {"name":"upm:poetry:conditional-reachability","value":"true"},
                child.get("properties", []),
            )
            self.assertFalse(any(
                item["ref"] == "pkg:pypi/parent@1.0.0"
                and "pkg:pypi/optional-child@2.0.0" in item.get("dependsOn", [])
                for item in document.get("dependencies", [])
            ))

    def test_spdx_optional_edge_is_not_flattened_into_depends_on(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
optional-child = {version = "2.0.0", optional = true}

[[package]]
name = "optional-child"
version = "2.0.0"
''')
            document = merge_python_lock_spdx(
                spdx_document(graph, created=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                [result],
            )
            by_name = {package["name"]: package["SPDXID"] for package in document["packages"]}

            self.assertIn("parent", by_name)
            self.assertIn("optional-child", by_name)
            self.assertFalse(any(
                relation["relationshipType"] == "DEPENDS_ON"
                and relation["spdxElementId"] == by_name["parent"]
                and relation["relatedSpdxElement"] == by_name["optional-child"]
                for relation in document["relationships"]
            ))

    def test_direct_requirement_marker_is_conditional_reachability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
[[package]]
name = "marked"
version = "4.0.0"
''', dependency="marked>=4; python_version >= '3.12'")
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])
            marked = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/marked@4.0.0")

            self.assertIn(
                {"name":"upm:poetry:conditional-reachability","value":"true"},
                marked.get("properties", []),
            )
            self.assertIn(
                {"name":"upm:poetry:reachability","value":"conditional"},
                marked.get("properties", []),
            )

    def test_non_registry_target_has_distinct_omission_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
localpkg = "*"

[[package]]
name = "localpkg"
version = "3.0.0"
[package.source]
type = "git"
url = "https://example.invalid/repo.git"
''')
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")

            self.assertIn(
                {"name":"upm:poetry:non-registry-edges-omitted","value":"1"},
                parent.get("properties", []),
            )
            self.assertNotIn("pkg:pypi/localpkg@3.0.0", {
                item.get("purl") for item in document["components"] if item.get("purl")
            })

    def test_missing_lock_candidate_is_unresolved_not_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, result = self._project(root, '''
[[package]]
name = "parent"
version = "1.0.0"
[package.dependencies]
missing = ">=9"
''')
            document = merge_python_lock_cyclonedx(cyclonedx_bom(graph), [result])
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")

            self.assertIn(
                {"name":"upm:poetry:unresolved-edges-omitted","value":"1"},
                parent.get("properties", []),
            )
            self.assertNotIn(
                {"name":"upm:poetry:ambiguous-edges-omitted","value":"1"},
                parent.get("properties", []),
            )


if __name__ == "__main__":
    unittest.main()
