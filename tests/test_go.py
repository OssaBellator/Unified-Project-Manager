from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.initializer import InitializationError, plan_initialization
from unified_project_manager.tasks import plan_native_task
from unified_project_manager.toolchains import NumericVersion, satisfies
from unified_project_manager.verifier import plan_native_verification


class GoTests(unittest.TestCase):
    def test_discovery_parses_requirements_checksums_and_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text('''module example.com/app

go 1.23.0

require (
  golang.org/x/text v0.22.0
  golang.org/x/sys v0.30.0 // indirect
)
''', encoding="utf-8")
            (root / "go.sum").write_text('''golang.org/x/text v0.22.0 h1:YWJjZA==
golang.org/x/text v0.22.0/go.mod h1:ZWZnaA==
''', encoding="utf-8")
            component = discover(root).components[0]
            self.assertEqual((component.ecosystem, component.manager, component.metadata["name"]), ("go", "go", "example.com/app"))
            self.assertEqual(component.toolchains[0].requirement, "1.23.0")
            self.assertEqual(
                [(dependency.name, dependency.scope) for dependency in component.dependencies],
                [("golang.org/x/sys", "indirect"), ("golang.org/x/text", "runtime")],
            )
            self.assertEqual(component.metadata["checksum_entries"], 2)
            self.assertEqual(component.resolved_packages, [])

    def test_go_version_is_minimum(self) -> None:
        version = NumericVersion.parse("go version go1.24.1 linux/amd64")
        assert version is not None
        self.assertTrue(satisfies("go", version, "1.23.0"))
        self.assertFalse(satisfies("go", version, "1.25"))

    def test_go_verifier_uses_tidy_diff_even_without_sum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.23\n", encoding="utf-8")
            plans, skips = plan_native_verification(discover(root))
            self.assertEqual(skips, [])
            self.assertEqual(plans[0].argv, ("go", "mod", "tidy", "-diff"))

    def test_go_init_requires_module_and_plans_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(InitializationError):
                plan_initialization(root, "service", "go")
            plan = plan_initialization(root, "service", "go", module="example.com/service")
            self.assertEqual(plan.argv, ("go", "mod", "init", "example.com/service"))

    def test_go_native_test_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.23\n", encoding="utf-8")
            plan = plan_native_task(discover(root), "test")
            self.assertEqual(plan.argv, ("go", "test", "./..."))


if __name__ == "__main__":
    unittest.main()
