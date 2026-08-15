from __future__ import annotations

import unittest
from pathlib import Path

from unified_project_manager.python_lock_graph import (
    PythonLockedPackage,
    PythonLockEdge,
    PythonLockGraphPlan,
    PythonLockGraphResult,
)
from unified_project_manager.python_lock_queries import query_python_lock_result


class PythonLockQueryContractTests(unittest.TestCase):
    def _result(
        self,
        *,
        manager: str = "poetry",
        packages: list[PythonLockedPackage],
        edges: list[PythonLockEdge],
    ) -> PythonLockGraphResult:
        component = ".:python"
        lockfile = Path("/tmp/poetry.lock" if manager == "poetry" else "/tmp/pdm.lock")
        return PythonLockGraphResult(
            PythonLockGraphPlan(component, manager, lockfile),
            packages,
            edges,
            (f"project:{component}",),
        )

    def _package(self, package_id: str, name: str, version: str) -> PythonLockedPackage:
        return PythonLockedPackage(".:python", package_id, name, version, "registry", ())

    def _edge(
        self,
        source: str,
        name: str,
        target: str | None,
        *,
        candidates: tuple[str, ...] = (),
        marker: str | None = None,
        optional: bool = False,
        ambiguous: bool = False,
    ) -> PythonLockEdge:
        return PythonLockEdge(
            ".:python", source, name, target, candidates,
            marker=marker, optional=optional, ambiguous=ambiguous,
        )

    def test_unconditional_query_contract_is_command_neutral(self) -> None:
        package = self._package("target#1", "target", "1.0.0")
        result = self._result(
            packages=[package],
            edges=[self._edge("project:.:python", "target", "target#1")],
        )

        query = query_python_lock_result(result, "target")
        payload = query.to_dict()

        self.assertEqual(payload["provider"], "poetry-lock")
        self.assertEqual(payload["scope"], "structured-lock-dependency-graph")
        self.assertTrue(payload["matched"])
        self.assertFalse(payload["uncertain"])
        self.assertEqual(payload["summary"], {
            "packages": 1,
            "unconditional_matches": 1,
            "conditional_matches": 0,
            "ambiguities": 0,
        })
        self.assertIn("not source/API/runtime", payload["interpretation"])

    def test_conditional_query_uses_same_contract_for_optional_or_marker_paths(self) -> None:
        package = self._package("target#1", "target", "1.0.0")
        result = self._result(
            manager="pdm",
            packages=[package],
            edges=[self._edge(
                "project:.:python", "target", "target#1",
                marker="sys_platform == 'linux'",
                optional=True,
            )],
        )

        query = query_python_lock_result(result, "target")
        payload = query.to_dict()

        self.assertEqual(payload["provider"], "pdm-lock")
        self.assertTrue(payload["uncertain"])
        self.assertEqual(payload["summary"]["conditional_matches"], 1)
        self.assertEqual(payload["summary"]["unconditional_matches"], 0)
        self.assertTrue(payload["packages"][0]["paths"][0]["conditional"])
        self.assertEqual(payload["packages"][0]["paths"][0]["optional_edges"], 1)
        self.assertEqual(payload["packages"][0]["paths"][0]["markers"], ["sys_platform == 'linux'"])

    def test_reachable_ambiguity_retains_conditional_path_without_fabricating_candidate_path(self) -> None:
        parent = self._package("parent#1", "parent", "1.0.0")
        shared_one = self._package("shared#1", "shared", "1.0.0")
        shared_two = self._package("shared#2", "shared", "2.0.0")
        result = self._result(
            packages=[parent, shared_one, shared_two],
            edges=[
                self._edge("project:.:python", "parent", "parent#1"),
                self._edge(
                    "parent#1", "shared", None,
                    candidates=("shared#1", "shared#2"),
                    marker="sys_platform == 'linux'",
                    optional=True,
                    ambiguous=True,
                ),
            ],
        )

        payload = query_python_lock_result(result, "shared").to_dict()

        self.assertTrue(payload["matched"])
        self.assertTrue(payload["uncertain"])
        self.assertEqual(payload["packages"], [])
        self.assertEqual(payload["summary"]["ambiguities"], 1)
        ambiguity = payload["ambiguities"][0]
        self.assertEqual(ambiguity["source"], "parent@1.0.0")
        self.assertEqual(ambiguity["candidate_ids"], ["shared#1", "shared#2"])
        self.assertTrue(ambiguity["optional"])
        self.assertTrue(ambiguity["conditional"])
        self.assertEqual(ambiguity["paths"][0]["nodes"][-1], "?shared")
        self.assertEqual(ambiguity["paths"][0]["markers"], ["sys_platform == 'linux'"])
        self.assertEqual(ambiguity["paths"][0]["optional_edges"], 1)


if __name__ == "__main__":
    unittest.main()
