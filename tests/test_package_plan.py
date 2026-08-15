from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.operations import OperationError
from unified_project_manager.package_plan import (
    dispatch_package_plan_command,
    package_execution_plan,
    validate_executor_package_spec,
)


class PackagePlanTests(unittest.TestCase):
    def test_node_plan_exports_stable_executor_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text('{"name":"frontend","packageManager":"npm@11"}', encoding="utf-8")
            (frontend / "package-lock.json").write_text("{}", encoding="utf-8")

            plan = package_execution_plan(discover(root), "add", selector="frontend", packages=("zod@^4",), dev=False)

            self.assertEqual(plan["schemaVersion"], 1)
            self.assertEqual(plan["operation"], "add")
            self.assertEqual(plan["component"], "frontend:node")
            self.assertEqual(plan["ecosystem"], "node")
            self.assertEqual(plan["manager"], "npm")
            self.assertEqual(plan["cwd"], "frontend")
            self.assertEqual(plan["packages"], ["zod@^4"])
            self.assertEqual(plan["argv"], ["npm", "install", "zod@^4"])
            self.assertEqual(plan["mutationScope"], {"workspace": True, "external": False})
            self.assertIs(plan["networkRequired"], True)

    def test_executor_contract_rejects_flag_source_path_and_whitespace_smuggling(self) -> None:
        rejected = (
            "--ignore-scripts",
            "file:../local",
            "https://example.com/pkg.tgz",
            "git+ssh://example.com/repo.git",
            "../local",
            "C:\\local\\pkg",
            "a package",
        )
        for package in rejected:
            with self.subTest(package=package):
                with self.assertRaises(OperationError):
                    validate_executor_package_spec("npm", package, operation="add")

    def test_executor_contract_keeps_useful_safe_native_specs(self) -> None:
        accepted = (
            ("npm", "@scope/pkg@^2"),
            ("uv", "requests>=2.32"),
            ("poetry", "requests@^2.32"),
            ("cargo", "serde@1.0"),
            ("go", "golang.org/x/text@v0.28.0"),
        )
        for manager, package in accepted:
            with self.subTest(manager=manager, package=package):
                self.assertEqual(validate_executor_package_spec(manager, package, operation="add"), package)

    def test_go_remove_rejects_versioned_input_before_none_is_appended(self) -> None:
        with self.assertRaises(OperationError):
            validate_executor_package_spec("go", "example.com/dep@v1.0.0", operation="remove")

    def test_package_plan_command_is_json_preview_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                code = dispatch_package_plan_command(["package-plan", "add", "zod", "--path", str(root)])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["argv"], ["npm", "install", "zod"])
            self.assertNotIn("executed", payload)


if __name__ == "__main__":
    unittest.main()
