from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.environment_inspection import inspect_environment
from unified_project_manager.models import Component, ProjectGraph


class EnvironmentInspectionTests(unittest.TestCase):
    def test_python_external_virtualenv_and_pythonpath_are_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "uv")])
            outside = Path(external)
            inside = root / "src"
            inside.mkdir()
            inspection = inspect_environment(graph, environ={
                "VIRTUAL_ENV": str(outside / "venv"),
                "PYTHONPATH": os.pathsep.join((str(inside), str(outside / "shared-src"))),
            })

            codes = {item.code for item in inspection.findings}
            self.assertIn("environment.python.external-virtualenv", codes)
            self.assertIn("environment.python.external-pythonpath", codes)
            pythonpath = [item for item in inspection.observations if item.variable == "PYTHONPATH"]
            self.assertEqual(len(pythonpath), 2)
            self.assertEqual({item.in_project for item in pythonpath}, {True, False})

    def test_project_local_virtualenv_is_observed_without_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "uv")])
            inspection = inspect_environment(graph, environ={
                "VIRTUAL_ENV": str(root / ".venv"),
            })
            self.assertEqual(inspection.findings, ())
            self.assertTrue(inspection.observations[0].in_project)

    def test_node_path_outside_project_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("node", root, "npm")])
            inspection = inspect_environment(graph, environ={
                "NODE_PATH": str(Path(external) / "node_modules"),
            })
            self.assertEqual(
                [item.code for item in inspection.findings],
                ["environment.node.external-node-path"],
            )

    def test_explicit_external_gowork_is_warning_but_off_mode_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("go", root, "go")])
            external_inspection = inspect_environment(graph, environ={
                "GOWORK": str(Path(external) / "go.work"),
            })
            off_inspection = inspect_environment(graph, environ={"GOWORK": "off"})

            self.assertEqual(
                [item.code for item in external_inspection.findings],
                ["environment.go.external-workspace"],
            )
            self.assertEqual(off_inspection.findings, ())
            self.assertEqual(off_inspection.observations[0].kind, "go-workspace-mode")
            self.assertIsNone(off_inspection.observations[0].in_project)

    def test_shared_cache_and_tool_homes_are_context_not_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("go", root / "go", "go"),
                Component("rust", root / "rust", "cargo"),
                Component("node", root / "node", "npm"),
            ])
            outside = Path(external)
            inspection = inspect_environment(graph, environ={
                "GOMODCACHE": str(outside / "gomodcache"),
                "GOPATH": str(outside / "gopath"),
                "CARGO_HOME": str(outside / "cargo"),
                "npm_config_prefix": str(outside / "npm-prefix"),
            })
            self.assertEqual(inspection.findings, ())
            self.assertEqual(len(inspection.observations), 4)
            self.assertTrue(all(item.in_project is False for item in inspection.observations))

    def test_irrelevant_ecosystem_specific_variables_are_not_dumped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("rust", root, "cargo")])
            inspection = inspect_environment(graph, environ={
                "VIRTUAL_ENV": "/secret/python/env",
                "NODE_PATH": "/secret/node/path",
                "UNRELATED_SECRET": "do-not-emit",
            })
            self.assertEqual(inspection.observations, ())
            self.assertEqual(inspection.findings, ())


if __name__ == "__main__":
    unittest.main()
