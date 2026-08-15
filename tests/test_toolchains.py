from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ToolchainRequirement
from unified_project_manager.toolchains import NumericVersion, satisfies_node, satisfies_python, satisfies_rust, toolchain_findings


class ToolchainVersionTests(unittest.TestCase):
    def test_node_common_semver_ranges(self) -> None:
        version = NumericVersion.parse("v20.11.1")
        assert version is not None
        self.assertTrue(satisfies_node(version, ">=18 <21"))
        self.assertTrue(satisfies_node(version, "^20.9.0 || >=22"))
        self.assertTrue(satisfies_node(version, "20.x"))
        self.assertFalse(satisfies_node(version, "^18.0.0"))

    def test_python_common_specifiers(self) -> None:
        version = NumericVersion.parse("Python 3.12.4")
        assert version is not None
        self.assertTrue(satisfies_python(version, ">=3.11,<3.13"))
        self.assertTrue(satisfies_python(version, "~=3.12"))
        self.assertTrue(satisfies_python(version, "==3.12.*"))
        self.assertFalse(satisfies_python(version, ">=3.13"))

    def test_rust_version_is_minimum(self) -> None:
        version = NumericVersion.parse("rustc 1.88.0")
        assert version is not None
        self.assertTrue(satisfies_rust(version, "1.80"))
        self.assertFalse(satisfies_rust(version, "1.90"))

    def test_findings_compare_each_component_requirement_but_read_version_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root=root, components=[
                Component("python", root / "a", "uv", toolchains=[ToolchainRequirement("python", ">=3.11")]),
                Component("python", root / "b", "uv", toolchains=[ToolchainRequirement("python", ">=3.14")]),
            ])
            calls = []

            def fake_run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "Python 3.13.2\n", "")

            findings = toolchain_findings(graph, which=lambda _name: "/bin/python", run=fake_run)
            self.assertEqual(len(calls), 1)
            mismatches = [finding for finding in findings if finding.code == "toolchain.version-mismatch"]
            self.assertEqual([finding.component for finding in mismatches], ["b:python"])

    def test_unsupported_requirement_is_informational(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root=root, components=[
                Component("node", root, "npm", toolchains=[ToolchainRequirement("node", "workspace:^20")]),
            ])

            def fake_run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, "v20.11.1\n", "")

            findings = toolchain_findings(graph, which=lambda _name: "/bin/node", run=fake_run)
            self.assertEqual(findings[0].code, "toolchain.requirement-unverified")
            self.assertEqual(findings[0].severity, "info")


if __name__ == "__main__":
    unittest.main()
