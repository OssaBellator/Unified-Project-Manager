from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.models import Component, ProjectGraph
from unified_project_manager.verifier import execute_verification, plan_native_verification


class NativeVerificationTests(unittest.TestCase):
    def test_plans_only_documented_non_mutating_verifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            components = [
                Component("node", root / "npm", "npm", lockfiles=["package-lock.json"]),
                Component("node", root / "bun", "bun", lockfiles=["bun.lock"]),
                Component("python", root / "uv", "uv", lockfiles=["uv.lock"]),
                Component("python", root / "pdm", "pdm", lockfiles=["pdm.lock"]),
                Component("rust", root / "rust", "cargo", lockfiles=["Cargo.lock"]),
                Component("node", root / "pnpm", "pnpm", lockfiles=["pnpm-lock.yaml"]),
            ]
            plans, skips = plan_native_verification(ProjectGraph(root, components))
            commands = {plan.manager: plan.argv for plan in plans}
            self.assertEqual(commands["uv"], ("uv", "lock", "--check"))
            self.assertIn("--dry-run", commands["npm"])
            self.assertIn("--dry-run", commands["bun"])
            self.assertEqual(commands["pdm"], ("pdm", "lock", "--check"))
            self.assertEqual(commands["cargo"], ("cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"))
            self.assertEqual([(skip.manager, skip.reason) for skip in skips], [("pnpm", "no documented non-mutating native verifier is configured")])

    def test_execute_captures_native_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("python", root, "uv", lockfiles=["uv.lock"])])
            plan = plan_native_verification(graph)[0][0]

            def fake_run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 2, "", "lockfile needs update\n")

            result = execute_verification(plan, run=fake_run, which=lambda _name: "/bin/uv")
            self.assertFalse(result.succeeded)
            self.assertEqual(result.returncode, 2)
            self.assertIn("needs update", result.stderr)

    def test_execute_uses_resolved_binary_and_go_component_disables_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("go", root, "go", manifests=["go.mod"])])
            plan = plan_native_verification(graph)[0][0]
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "", "")

            result = execute_verification(plan, run=fake_run, which=lambda _name: "/toolchains/go")
            self.assertTrue(result.succeeded)
            self.assertEqual(calls[0][0][0], "/toolchains/go")
            self.assertEqual(calls[0][1]["env"]["GOWORK"], "off")

    def test_conflicting_lockfiles_are_skipped_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = ProjectGraph(root, [Component("node", root, "npm", lockfiles=["package-lock.json", "yarn.lock"])])
            plans, skips = plan_native_verification(graph)
            self.assertEqual(plans, [])
            self.assertEqual(skips[0].reason, "conflicting native lockfiles")


if __name__ == "__main__":
    unittest.main()
