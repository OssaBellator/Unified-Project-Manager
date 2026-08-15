from __future__ import annotations

import unittest
from pathlib import Path

from unified_project_manager.python_lock_graph import (
    PythonLockedPackage,
    PythonLockEdge,
    PythonLockGraphPlan,
    PythonLockGraphResult,
)
from unified_project_manager.security_impact import correlate_advisory_impact


class PythonLockSecurityImpactTests(unittest.TestCase):
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

    def _result(self, packages: list[PythonLockedPackage], edges: list[PythonLockEdge]) -> PythonLockGraphResult:
        return PythonLockGraphResult(
            PythonLockGraphPlan(".:python", "poetry", Path("/tmp/poetry.lock")),
            packages,
            edges,
            ("project:.:python",),
        )

    def _report(self, name: str, version: str, advisory: str = "PYSEC-TEST") -> dict:
        return {
            "results": [{
                "packages": [{
                    "package": {"name": name, "version": version, "ecosystem": "PyPI"},
                    "vulnerabilities": [{"id": advisory}],
                }],
            }],
        }

    def test_transitive_possible_finding_keeps_ambiguity_hop(self) -> None:
        parent = self._package("parent#1", "parent", "1.0.0")
        shared_one = self._package("shared#1", "shared", "1.0.0")
        shared_two = self._package("shared#2", "shared", "2.0.0")
        leaf = self._package("leaf#1", "leaf", "3.0.0")
        result = self._result(
            [parent, shared_one, shared_two, leaf],
            [
                self._edge("project:.:python", "parent", "parent#1"),
                self._edge(
                    "parent#1", "shared", None,
                    candidates=("shared#1", "shared#2"), ambiguous=True,
                ),
                self._edge("shared#1", "leaf", "leaf#1"),
            ],
        )

        impacts = correlate_advisory_impact(
            self._report("leaf", "3.0.0"),
            python_lock_results=[result],
        )

        self.assertEqual(len(impacts), 1)
        impact = impacts[0]
        self.assertEqual(impact.provider, "poetry-lock")
        self.assertEqual(impact.evidence["reachability"], "possible-via-ambiguous-lock-reference")
        self.assertIn("?shared", impact.paths[0])
        self.assertEqual(impact.paths[0][-1], "leaf@3.0.0")

    def test_resolved_and_possible_paths_for_same_occurrence_are_consolidated(self) -> None:
        direct = self._package("direct#1", "target", "4.0.0")
        parent = self._package("parent#1", "parent", "1.0.0")
        branch_one = self._package("branch#1", "branch", "1.0.0")
        branch_two = self._package("branch#2", "branch", "2.0.0")
        result = self._result(
            [direct, parent, branch_one, branch_two],
            [
                self._edge("project:.:python", "target", "direct#1"),
                self._edge("project:.:python", "parent", "parent#1"),
                self._edge(
                    "parent#1", "branch", None,
                    candidates=("branch#1", "branch#2"), ambiguous=True,
                ),
                self._edge("branch#1", "target", "direct#1"),
            ],
        )

        impacts = correlate_advisory_impact(
            self._report("target", "4.0.0", "PYSEC-CONSOLIDATE"),
            python_lock_results=[result],
        )

        self.assertEqual(len(impacts), 1)
        impact = impacts[0]
        self.assertEqual(impact.evidence["reachability"], "resolved")
        self.assertTrue(impact.evidence["unconditional"])
        self.assertEqual(len(impact.evidence["path_conditions"]), 1)
        self.assertEqual(len(impact.evidence["possible_path_conditions"]), 1)
        self.assertEqual(len(impact.paths), 2)
        self.assertTrue(any("?branch" in path for path in impact.paths))
        self.assertTrue(any("?branch" not in path for path in impact.paths))


if __name__ == "__main__":
    unittest.main()
