from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.native_cyclonedx import build_native_cyclonedx
from unified_project_manager.provider_registry import provider_summary
from unified_project_manager.root_entrypoint import main
from unified_project_manager.security_impact import correlate_advisory_impact


_POETRY_LOCK = '''
[[package]]
name = "parent"
version = "1.0.0"
groups = ["main"]
[package.dependencies]
child = { version = ">=2", markers = "python_version >= '3.12'" }
optional-child = { version = ">=3", optional = true }
shared = ">=1"

[[package]]
name = "child"
version = "2.0.0"
groups = ["main"]

[[package]]
name = "optional-child"
version = "3.0.0"
groups = ["main"]

[[package]]
name = "shared"
version = "1.0.0"
groups = ["main"]
[package.dependencies]
leaf = "*"

[[package]]
name = "shared"
version = "2.0.0"
groups = ["main"]

[[package]]
name = "leaf"
version = "4.0.0"
groups = ["main"]

[[package]]
name = "orphan"
version = "9.9.9"
groups = ["main"]

[metadata]
lock-version = "2.1"
'''


_PDM_LOCK = '''
[metadata]
lock_version = "4.5.0"

[[package]]
name = "parent"
version = "1.0.0"
dependencies = ["child>=2; sys_platform == 'linux'"]

[[package]]
name = "child"
version = "2.0.0"
'''


class PythonLockPublicProviderTests(unittest.TestCase):
    def _poetry_project(self, root: Path) -> None:
        (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent>=1"]

[tool.poetry]
name = "app"
version = "0.1.0"
''', encoding="utf-8")
        (root / "poetry.lock").write_text(_POETRY_LOCK, encoding="utf-8")

    def _pdm_project(self, root: Path) -> None:
        (root / "pyproject.toml").write_text('''
[project]
name = "app"
version = "0.1.0"
dependencies = ["parent>=1"]

[tool.pdm]
''', encoding="utf-8")
        (root / "pdm.lock").write_text(_PDM_LOCK, encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_poetry_graph_preview_and_execution_are_static_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._poetry_project(root)

            preview_code, preview = self._json([
                "graph", str(root), "--native", "--preview", "--json",
            ])
            graph_code, graph = self._json([
                "graph", str(root), "--native", "--json",
            ])

            self.assertEqual(preview_code, 0)
            plan = next(item for item in preview["plans"] if item["provider"] == "poetry-lock")
            self.assertEqual(plan["commands"], [])
            self.assertFalse(plan["execution"])
            self.assertFalse(plan["network"])
            self.assertFalse(plan["mutation"])
            self.assertEqual(plan["certainty"], "conditional-and-ambiguity-preserving")

            self.assertEqual(graph_code, 0)
            result = next(item for item in graph["results"] if item["provider"] == "poetry-lock")
            self.assertTrue(result["succeeded"])
            child = next(edge for edge in result["edges"] if edge["dependency_name"] == "child")
            self.assertEqual(child["marker"], "python_version >= '3.12'")
            shared = next(edge for edge in result["edges"] if edge["dependency_name"] == "shared")
            self.assertTrue(shared["ambiguous"])
            self.assertEqual(len(shared["candidate_ids"]), 2)

    def test_poetry_why_and_impact_share_certainty_aware_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._poetry_project(root)

            why_code, why = self._json(["why", "child", str(root), "--native", "--json"])
            impact_code, impact = self._json(["impact", "shared", str(root), "--native", "--json"])

            self.assertEqual(why_code, 0)
            answer = next(item for item in why["answers"] if item["provider"] == "poetry-lock")
            self.assertEqual(answer["scope"], "structured-lock-dependency-graph")
            self.assertTrue(answer["matched"])
            self.assertTrue(answer["uncertain"])
            self.assertFalse(answer["packages"][0]["unconditional"])
            self.assertEqual(
                answer["packages"][0]["paths"][0]["markers"],
                ["python_version >= '3.12'"],
            )

            self.assertEqual(impact_code, 0)
            shared = next(item for item in impact["impacts"] if item["provider"] == "poetry-lock")
            self.assertEqual(shared["packages"], [])
            self.assertEqual(len(shared["possible_packages"]), 2)
            self.assertTrue(all(item["possible"] for item in shared["possible_packages"]))
            self.assertEqual(len(shared["ambiguities"]), 1)
            ambiguity = shared["ambiguities"][0]
            self.assertEqual(ambiguity["paths"][0]["nodes"][-1], "?shared")
            self.assertEqual(len(ambiguity["candidate_ids"]), 2)

            leaf_code, leaf_impact = self._json(["impact", "leaf", str(root), "--native", "--json"])
            self.assertEqual(leaf_code, 0)
            leaf = next(item for item in leaf_impact["impacts"] if item["provider"] == "poetry-lock")
            self.assertEqual(leaf["packages"], [])
            self.assertEqual(len(leaf["possible_packages"]), 1)
            path = leaf["possible_packages"][0]["paths"][0]["nodes"]
            self.assertIn("?shared", path)
            self.assertEqual(path[-1], "leaf@4.0.0")

    def test_poetry_native_sbom_is_reachable_only_and_conditional_edges_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._poetry_project(root)

            code, document = self._json(["sbom", str(root), "--native"])

            self.assertEqual(code, 0)
            purls = {item.get("purl") for item in document.get("components", []) if item.get("purl")}
            self.assertIn("pkg:pypi/parent@1.0.0", purls)
            self.assertIn("pkg:pypi/child@2.0.0", purls)
            self.assertIn("pkg:pypi/leaf@4.0.0", purls)
            self.assertNotIn("pkg:pypi/orphan@9.9.9", purls)
            parent = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/parent@1.0.0")
            properties = {(item["name"], item["value"]) for item in parent.get("properties", [])}
            self.assertIn(("upm:poetry:conditional-edges-omitted", "2"), properties)
            self.assertIn(("upm:poetry:ambiguous-edges-omitted", "1"), properties)
            leaf = next(item for item in document["components"] if item.get("purl") == "pkg:pypi/leaf@4.0.0")
            self.assertIn(
                {"name": "upm:poetry:reachability", "value": "possible"},
                leaf.get("properties", []),
            )
            self.assertFalse(any(
                item["ref"] == "pkg:pypi/parent@1.0.0"
                and "pkg:pypi/child@2.0.0" in item.get("dependsOn", [])
                for item in document.get("dependencies", [])
            ))

    def test_poetry_provider_status_and_advisory_paths_use_same_retained_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._poetry_project(root)
            graph = discover(root)

            summary = provider_summary(graph)
            self.assertEqual(summary["supported_components"], 1)
            self.assertEqual(summary["providers"], ["poetry-lock"])

            inventory = build_native_cyclonedx(graph)
            report = {
                "results": [{
                    "packages": [
                        {
                            "package": {"name": "child", "ecosystem": "PyPI", "version": "2.0.0"},
                            "vulnerabilities": [{"id": "OSV-CHILD"}],
                        },
                        {
                            "package": {"name": "shared", "ecosystem": "PyPI", "version": "1.0.0"},
                            "vulnerabilities": [{"id": "OSV-SHARED"}],
                        },
                        {
                            "package": {"name": "leaf", "ecosystem": "PyPI", "version": "4.0.0"},
                            "vulnerabilities": [{"id": "OSV-LEAF"}],
                        },
                    ],
                }],
            }
            impacts = correlate_advisory_impact(
                report,
                python_lock_results=inventory.python_lock_results,
            )

            child = next(item for item in impacts if item.advisory_id == "OSV-CHILD")
            self.assertEqual(child.provider, "poetry-lock")
            self.assertFalse(child.evidence["unconditional"])
            self.assertEqual(child.evidence["path_conditions"][0]["markers"], ["python_version >= '3.12'"])

            shared = next(item for item in impacts if item.advisory_id == "OSV-SHARED")
            self.assertEqual(shared.evidence["reachability"], "possible-via-ambiguous-lock-reference")
            self.assertIn("?shared", shared.paths[0])
            self.assertEqual(shared.paths[0][-1], "shared@1.0.0")

            leaf = next(item for item in impacts if item.advisory_id == "OSV-LEAF")
            self.assertEqual(leaf.evidence["reachability"], "possible-via-ambiguous-lock-reference")
            self.assertIn("?shared", leaf.paths[0])
            self.assertEqual(leaf.paths[0][-1], "leaf@4.0.0")

    def test_pdm_is_promoted_with_same_static_provider_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._pdm_project(root)

            graph_code, graph = self._json(["graph", str(root), "--native", "--json"])
            why_code, why = self._json(["why", "child", str(root), "--native", "--json"])

            self.assertEqual(graph_code, 0)
            result = next(item for item in graph["results"] if item["provider"] == "pdm-lock")
            self.assertTrue(result["succeeded"])
            self.assertEqual(result["plan"]["manager"], "pdm")

            self.assertEqual(why_code, 0)
            answer = next(item for item in why["answers"] if item["provider"] == "pdm-lock")
            self.assertEqual(answer["scope"], "structured-lock-dependency-graph")
            self.assertEqual(answer["packages"][0]["paths"][0]["markers"], ["sys_platform == 'linux'"])


if __name__ == "__main__":
    unittest.main()
