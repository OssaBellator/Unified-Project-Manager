from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.operations import (
    OperationError,
    execute_plan,
    plan_operation,
    plan_operations,
    render_command,
)


class OperationTests(unittest.TestCase):
    def test_component_selection_is_required_for_multi_component_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "a" / "package-lock.json").write_text("{}", encoding="utf-8")
            (root / "b" / "Cargo.toml").write_text('[package]\nname="b"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "b" / "Cargo.lock").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(OperationError, "Multiple components"):
                plan_operation(discover(root), "install")

    def test_plans_manager_specific_commands(self) -> None:
        cases = [
            ("npm", "package-lock.json", "add", ("react",), True, ("npm", "install", "--save-dev", "react")),
            ("pnpm", "pnpm-lock.yaml", "sync", (), False, ("pnpm", "install", "--frozen-lockfile")),
            ("bun", "bun.lock", "remove", ("zod",), False, ("bun", "remove", "zod")),
        ]
        for manager, lock, operation, packages, dev, expected in cases:
            with self.subTest(manager=manager, operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "package.json").write_text(json.dumps({"packageManager": f"{manager}@10"}), encoding="utf-8")
                (root / lock).write_text("", encoding="utf-8")
                plan = plan_operation(discover(root), operation, packages=packages, dev=dev)
                self.assertEqual(plan.argv, expected)

    def test_yarn_sync_is_version_aware(self) -> None:
        for declared, flag in (("yarn@1.22.22", "--frozen-lockfile"), ("yarn@4.9.2", "--immutable")):
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "package.json").write_text(json.dumps({"packageManager": declared}), encoding="utf-8")
                (root / "yarn.lock").write_text("", encoding="utf-8")
                self.assertEqual(plan_operation(discover(root), "sync").argv, ("yarn", "install", flag))

    def test_uv_and_cargo_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text('[project]\nname="x"\n', encoding="utf-8")
            (root / "uv.lock").write_text("", encoding="utf-8")
            self.assertEqual(plan_operation(discover(root), "sync").argv, ("uv", "sync", "--locked"))
            self.assertEqual(plan_operation(discover(root), "add", packages=("pytest",), dev=True).argv, ("uv", "add", "--dev", "pytest"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text("", encoding="utf-8")
            self.assertEqual(plan_operation(discover(root), "install").argv, ("cargo", "fetch"))
            self.assertEqual(plan_operation(discover(root), "sync").argv, ("cargo", "fetch", "--locked"))

    def test_pip_refuses_manifest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("requests==2\n", encoding="utf-8")
            graph = discover(root)
            self.assertEqual(plan_operation(graph, "install").argv, ("python", "-m", "pip", "install", "-r", "requirements.txt"))
            with self.assertRaisesRegex(OperationError, "safe native"):
                plan_operation(graph, "add", packages=("flask",))

    def test_sync_requires_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            with self.assertRaisesRegex(OperationError, "without a native lockfile"):
                plan_operation(discover(root), "sync")

    def test_execute_plan_captures_result_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            plan = plan_operation(discover(root), "sync")
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs["cwd"]))
                return subprocess.CompletedProcess(argv, 0, "installed\n", "")

            result = execute_plan(plan, root, run=fake_run, which=lambda _name: "/bin/tool")
            self.assertEqual(calls[0][0], ["npm", "ci"])
            self.assertEqual(result.stdout, "installed\n")
            self.assertTrue(result.succeeded)
            self.assertIsNotNone(result.verification)

    def test_render_command_shell_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            plan = plan_operation(discover(root), "add", packages=("a package",))
            self.assertEqual(render_command(plan), "npm install 'a package'")

    def test_conflicting_manager_state_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"pnpm@10"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(OperationError, "manifest declares pnpm"):
                plan_operation(discover(root), "add", packages=("react",))

    def test_plan_operations_all_requires_every_component_to_be_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "a"
            python = root / "b"
            node.mkdir()
            python.mkdir()
            (node / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (node / "package-lock.json").write_text("{}", encoding="utf-8")
            (python / "requirements.txt").write_text("requests==2\n", encoding="utf-8")
            with self.assertRaisesRegex(OperationError, "every component is safe"):
                plan_operations(discover(root), "sync", all_components=True)


if __name__ == "__main__":
    unittest.main()
