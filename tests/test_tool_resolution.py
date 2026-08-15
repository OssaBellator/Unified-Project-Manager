from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ToolchainRequirement
from unified_project_manager.tool_resolution import collect_tool_resolution


class ToolResolutionTests(unittest.TestCase):
    def test_default_resolution_executes_no_tool_or_version_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "node",
                    root,
                    "pnpm",
                    metadata={"package_manager_declared": "pnpm@10"},
                    toolchains=[ToolchainRequirement("node", ">=22")],
                )
            ])
            calls = []

            report = collect_tool_resolution(
                graph,
                which=lambda name: f"/shims/{name}",
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
            )

            self.assertEqual(calls, [])
            self.assertFalse(report.version_probes_executed)
            self.assertEqual(report.network_guarantee, "no-execution")
            data = report.to_dict()
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["mutation_executed"])
            self.assertTrue(all(item.version is None for item in report.observations))
            self.assertTrue(all(item.version_returncode is None for item in report.observations))
            self.assertEqual(
                {item.resolved_path for item in report.observations},
                {"/shims/pnpm", "/shims/node"},
            )

    def test_opt_in_probe_uses_exact_resolved_path_and_corepack_network_mitigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("node", root, "pnpm")])
            calls = []

            def run(argv, **kwargs):
                calls.append((list(argv), kwargs))
                return subprocess.CompletedProcess(argv, 0, "10.7.0\n", "")

            report = collect_tool_resolution(
                graph,
                probe_versions=True,
                which=lambda _name: "/corepack/pnpm",
                run=run,
                environ={"PATH": "/corepack"},
            )

            self.assertEqual(calls[0][0], ["/corepack/pnpm", "--version"])
            self.assertEqual(calls[0][1]["env"]["COREPACK_ENABLE_NETWORK"], "0")
            self.assertEqual(calls[0][1]["env"]["PATH"], "/corepack")
            self.assertTrue(report.version_probes_executed)
            self.assertEqual(report.network_guarantee, "not-guaranteed")
            self.assertIsNone(report.to_dict()["network_executed"])
            self.assertEqual(report.observations[0].version, "10.7.0")
            self.assertEqual(report.observations[0].version_returncode, 0)

    def test_probe_cache_is_keyed_by_exact_resolved_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("node", root / "a", "npm"),
                Component("node", root / "b", "npm"),
            ])
            calls = []

            def run(argv, **kwargs):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "11.0.0\n", "")

            report = collect_tool_resolution(
                graph,
                probe_versions=True,
                which=lambda _name: "/usr/local/bin/npm",
                run=run,
            )

            self.assertEqual(calls, [["/usr/local/bin/npm", "--version"]])
            self.assertEqual(len(report.observations), 2)

    def test_missing_tool_is_observed_without_attempting_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("rust", root, "cargo")])
            calls = []

            report = collect_tool_resolution(
                graph,
                probe_versions=True,
                which=lambda _name: None,
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
            )

            self.assertEqual(calls, [])
            observation = report.observations[0]
            self.assertFalse(observation.available)
            self.assertIsNone(observation.resolved_path)
            self.assertIsNone(observation.version_returncode)

    def test_probe_oserror_is_distinct_from_unavailable_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "uv")])

            def run(_argv, **_kwargs):
                raise OSError("cannot execute")

            report = collect_tool_resolution(
                graph,
                probe_versions=True,
                which=lambda _name: "/opt/uv",
                run=run,
            )
            observation = report.observations[0]

            self.assertTrue(observation.available)
            self.assertEqual(observation.resolved_path, "/opt/uv")
            self.assertEqual(observation.version_returncode, 127)
            self.assertIn("cannot execute", observation.stderr)

    def test_requirement_divergence_does_not_execute_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "node",
                    root / "a",
                    "npm",
                    metadata={"package_manager_declared": "npm@10"},
                    toolchains=[ToolchainRequirement("node", ">=20")],
                ),
                Component(
                    "node",
                    root / "b",
                    "npm",
                    metadata={"package_manager_declared": "npm@11"},
                    toolchains=[ToolchainRequirement("node", ">=22")],
                ),
            ])
            calls = []

            report = collect_tool_resolution(
                graph,
                which=lambda name: f"/bin/{name}",
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
            )

            self.assertEqual(calls, [])
            by_key = {(item.role, item.name): item for item in report.divergences}
            self.assertEqual(by_key[("manager", "npm")].requirements, ("10", "11"))
            self.assertEqual(by_key[("toolchain", "node")].requirements, (">=20", ">=22"))

    def test_pip_probe_identity_is_python_module_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "pip")])
            report = collect_tool_resolution(
                graph,
                which=lambda name: "/venv/bin/python" if name == "python" else None,
            )
            observation = report.observations[0]
            self.assertEqual(observation.probe_command, ("python", "-m", "pip", "--version"))
            self.assertEqual(observation.resolved_path, "/venv/bin/python")


if __name__ == "__main__":
    unittest.main()
