from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph, ToolchainRequirement
from unified_project_manager.tool_inventory import collect_tool_inventory


class ToolInventoryTests(unittest.TestCase):
    def test_exact_resolved_binary_is_used_and_duplicate_probe_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("node", root / "a", "npm"),
                Component("node", root / "b", "npm"),
            ])
            calls: list[list[str]] = []

            def which(name: str) -> str | None:
                return f"/toolchain/{name}"

            def run(argv, **kwargs):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "11.2.0\n", "")

            inventory = collect_tool_inventory(graph, which=which, run=run)

            self.assertEqual(calls, [["/toolchain/npm", "--version"]])
            self.assertEqual(len(inventory.resolutions), 2)
            self.assertEqual({item.resolved_path for item in inventory.resolutions}, {"/toolchain/npm"})
            self.assertEqual({item.version for item in inventory.resolutions}, {"11.2.0"})
            self.assertTrue(all(item.available for item in inventory.resolutions))

    def test_manager_and_toolchain_requirements_are_reported_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component(
                    "node",
                    root,
                    "pnpm",
                    metadata={"package_manager_declared": "pnpm@10.7.0"},
                    toolchains=[ToolchainRequirement("node", ">=22")],
                )
            ])

            def run(argv, **kwargs):
                output = "10.7.0\n" if argv[0].endswith("pnpm") else "v22.14.0\n"
                return subprocess.CompletedProcess(argv, 0, output, "")

            inventory = collect_tool_inventory(
                graph,
                which=lambda name: f"/bin/{name}",
                run=run,
            )
            by_role = {item.role: item for item in inventory.resolutions}

            self.assertEqual(by_role["manager"].name, "pnpm")
            self.assertEqual(by_role["manager"].requirement, "10.7.0")
            self.assertEqual(by_role["toolchain"].name, "node")
            self.assertEqual(by_role["toolchain"].requirement, ">=22")

    def test_requirement_divergence_is_cross_component_evidence_not_version_guessing(self) -> None:
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

            inventory = collect_tool_inventory(
                graph,
                which=lambda name: f"/bin/{name}",
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "1.0.0\n", ""),
            )
            by_key = {(item.role, item.name): item for item in inventory.divergences}

            self.assertEqual(by_key[("manager", "npm")].requirements, ("10", "11"))
            self.assertEqual(by_key[("toolchain", "node")].requirements, (">=20", ">=22"))
            self.assertEqual(
                by_key[("manager", "npm")].components,
                ("a:node", "b:node"),
            )

    def test_missing_tool_is_reported_without_running_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [
                Component("rust", root, "cargo", toolchains=[ToolchainRequirement("rust", "1.85")]),
            ])
            calls = []

            inventory = collect_tool_inventory(
                graph,
                which=lambda _name: None,
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
            )

            self.assertEqual(calls, [])
            self.assertEqual(len(inventory.resolutions), 2)
            self.assertTrue(all(not item.available for item in inventory.resolutions))
            self.assertTrue(all(item.version is None for item in inventory.resolutions))

    def test_version_probe_failure_preserves_resolved_path_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "uv")])

            inventory = collect_tool_inventory(
                graph,
                which=lambda name: f"/opt/{name}",
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 2, "", "broken config\n"),
            )
            resolution = inventory.resolutions[0]

            self.assertTrue(resolution.available)
            self.assertEqual(resolution.resolved_path, "/opt/uv")
            self.assertEqual(resolution.version_returncode, 2)
            self.assertEqual(resolution.version, "broken config")
            self.assertEqual(resolution.stderr, "broken config\n")

    def test_pip_manager_uses_python_module_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "pip")])
            calls = []

            def run(argv, **kwargs):
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "pip 25.1 from /x/pip\n", "")

            inventory = collect_tool_inventory(
                graph,
                which=lambda name: "/venv/bin/python" if name == "python" else None,
                run=run,
            )

            self.assertEqual(calls, [["/venv/bin/python", "-m", "pip", "--version"]])
            self.assertEqual(inventory.resolutions[0].version, "pip 25.1 from /x/pip")


if __name__ == "__main__":
    unittest.main()
