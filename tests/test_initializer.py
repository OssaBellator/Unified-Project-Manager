from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.initializer import (
    InitializationError,
    execute_initialization,
    plan_initialization,
)


class InitializerTests(unittest.TestCase):
    def test_plans_native_noninteractive_initializers(self) -> None:
        cases = (
            ("node", "npm", False, ("npm", "init", "--yes")),
            ("node", "pnpm", False, ("pnpm", "init", "--bare", "--init-package-manager")),
            ("node", "bun", False, ("bun", "init", "--yes")),
            ("python", "uv", False, ("uv", "init", ".")),
            ("python", "uv", True, ("uv", "init", "--lib", ".")),
            ("rust", "cargo", True, ("cargo", "init", ".", "--vcs", "none", "--lib")),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, (ecosystem, manager, library, expected) in enumerate(cases):
                target = f"project-{index}"
                plan = plan_initialization(root, target, ecosystem, manager, library=library)
                self.assertEqual(plan.argv, expected)
                self.assertEqual(plan.cwd, root / target)

    def test_refuses_nonempty_or_escaping_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            (existing / "README.md").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(InitializationError, "new or empty"):
                plan_initialization(root, existing, "node")
            with self.assertRaisesRegex(InitializationError, "within"):
                plan_initialization(root, "../outside", "node")

    def test_unsupported_manager_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(InitializationError, "cannot initialize"):
                plan_initialization(root, "project", "python", "poetry")

    def test_execute_creates_target_only_when_manager_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = plan_initialization(root, "project", "node", "npm")
            missing = execute_initialization(plan, root, which=lambda _name: None)
            self.assertEqual(missing.returncode, 127)
            self.assertFalse(plan.cwd.exists())

            calls = []

            def fake_run(argv, **kwargs):
                calls.append((argv, kwargs["cwd"]))
                (kwargs["cwd"] / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "created\n", "")

            result = execute_initialization(plan, root, run=fake_run, which=lambda _name: "/bin/tool")
            self.assertEqual(calls[0][0], ["npm", "init", "--yes"])
            self.assertTrue(plan.cwd.is_dir())
            self.assertEqual(result.returncode, 0)
            self.assertIsNotNone(result.verification)


if __name__ == "__main__":
    unittest.main()
