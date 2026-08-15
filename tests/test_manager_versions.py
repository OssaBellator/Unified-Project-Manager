from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.manager_versions import manager_version_findings
from unified_project_manager.models import Component, ProjectGraph


class ManagerVersionTests(unittest.TestCase):
    def test_mismatch_is_reported_and_version_read_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            graph = ProjectGraph(root, [
                Component("node", root / "a", "pnpm", metadata={"package_manager_declared": "pnpm@^10.2.0"}),
                Component("node", root / "b", "pnpm", metadata={"package_manager_declared": "pnpm@>=11"}),
            ])

            def run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "10.2.1\n", "")

            findings = manager_version_findings(graph, which=lambda _name: "/bin/pnpm", run=run)
            self.assertEqual(len(calls), 1)
            self.assertEqual([finding.component for finding in findings if finding.code == "manager.version-mismatch"], ["b:node"])

    def test_matching_exact_version_has_no_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("node", root, "npm", metadata={"package_manager_declared": "npm@11.1.0"})])

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, "11.1.0\n", "")

            self.assertEqual(manager_version_findings(graph, which=lambda _name: "/bin/npm", run=run), [])

    def test_unknown_range_is_informational(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("node", root, "yarn", metadata={"package_manager_declared": "yarn@workspace:4"})])

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, "4.2.0\n", "")

            findings = manager_version_findings(graph, which=lambda _name: "/bin/yarn", run=run)
            self.assertEqual(findings[0].code, "manager.requirement-unverified")
            self.assertEqual(findings[0].severity, "info")


if __name__ == "__main__":
    unittest.main()
