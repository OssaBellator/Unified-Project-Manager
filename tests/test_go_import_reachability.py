from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.go_import_reachability import collect_go_import_reachability
from unified_project_manager.models import ProjectGraph
from unified_project_manager.native_graph import NativeGraphSkip, NativeWhyResult


class GoImportReachabilityTests(unittest.TestCase):
    def _graph(self, root: Path) -> ProjectGraph:
        return ProjectGraph(root=root, components=[])

    def _impact(self, advisory: str, *, component: str = ".:go", module: str = "example.com/dep") -> dict:
        return {
            "advisory_id": advisory,
            "ecosystem": "Go",
            "package": module,
            "version": "v1.2.3",
            "provider": "go-modules",
            "scope": "module-requirement",
            "component": component,
            "paths": [["example.com/app", module]],
            "evidence": {"module": module, "effective_name": module},
        }

    def test_reachable_import_path_is_separate_from_build_runtime_and_exploitability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))

            def query(_graph, module, selector=None):
                self.assertEqual(module, "example.com/dep")
                self.assertEqual(selector, ".:go")
                return [NativeWhyResult(
                    ".:go", "go", module, True,
                    ("example.com/app/pkg", "example.com/dep/subpkg"),
                    0,
                )], []

            rows = collect_go_import_reachability(graph, [self._impact("GO-TEST-1")], query=query)

            self.assertEqual(len(rows), 1)
            data = rows[0].to_dict()
            self.assertEqual(data["state"], "package-import-reachable")
            self.assertEqual(data["scope"], "package-import-graph")
            self.assertEqual(data["import_path"], ["example.com/app/pkg", "example.com/dep/subpkg"])
            self.assertEqual(data["dependency_paths"], [["example.com/app", "example.com/dep"]])
            self.assertEqual(data["build_constraints"], "any-tags")
            self.assertEqual(data["current_build_configuration_reachability"], "not-evaluated")
            self.assertEqual(data["api_reachability"], "not-evaluated")
            self.assertEqual(data["runtime_reachability"], "not-evaluated")
            self.assertEqual(data["exploitability"], "not-established")
            self.assertTrue(data["test_imports_may_contribute"])
            self.assertFalse(data["persisted"])
            self.assertIn("any-build-tag", data["interpretation"])

    def test_not_import_reachable_is_an_explicit_successful_negative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))

            def query(_graph, module, selector=None):
                return [NativeWhyResult(".:go", "go", module, False, (), 0)], []

            row = collect_go_import_reachability(graph, [self._impact("GO-TEST-2")], query=query)[0]
            self.assertEqual(row.state, "not-package-import-reachable")
            self.assertEqual(row.returncode, 0)
            self.assertEqual(row.import_path, ())
            self.assertIsNone(row.error)
            data = row.to_dict()
            self.assertEqual(data["build_constraints"], "any-tags")
            self.assertEqual(data["current_build_configuration_reachability"], "not-evaluated")

    def test_failed_query_is_not_converted_to_not_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))

            def query(_graph, module, selector=None):
                return [NativeWhyResult(".:go", "go", module, False, (), 1, "missing package data")], []

            row = collect_go_import_reachability(graph, [self._impact("GO-TEST-3")], query=query)[0]
            self.assertEqual(row.state, "query-failed")
            self.assertEqual(row.returncode, 1)
            self.assertEqual(row.error, "missing package data")

    def test_provider_skip_is_query_failure_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))

            def query(_graph, module, selector=None):
                return [], [NativeGraphSkip(".:go", "go", "go", "go executable unavailable")]

            row = collect_go_import_reachability(graph, [self._impact("GO-TEST-4")], query=query)[0]
            self.assertEqual(row.state, "query-failed")
            self.assertIn("go executable unavailable", row.error or "")

    def test_same_component_module_is_queried_once_for_multiple_advisories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))
            calls = 0

            def query(_graph, module, selector=None):
                nonlocal calls
                calls += 1
                return [NativeWhyResult(".:go", "go", module, True, ("app/pkg", "dep/pkg"), 0)], []

            rows = collect_go_import_reachability(
                graph,
                [self._impact("GO-TEST-A"), self._impact("GO-TEST-B")],
                query=query,
            )

            self.assertEqual(calls, 1)
            self.assertEqual({row.advisory_id for row in rows}, {"GO-TEST-A", "GO-TEST-B"})

    def test_non_go_dependency_impacts_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = self._graph(Path(temporary))
            impact = self._impact("GHSA-NODE")
            impact["provider"] = "npm-lock-tree"

            def query(*_args, **_kwargs):
                raise AssertionError("non-Go impact must not trigger a Go source query")

            self.assertEqual(collect_go_import_reachability(graph, [impact], query=query), [])


if __name__ == "__main__":
    unittest.main()
