from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from unified_project_manager.discovery import discover
from unified_project_manager.entrypoint import main
from unified_project_manager.native_exec import NativeExecError, execute_native_exec, plan_native_exec
from unified_project_manager.status import project_status


class NativeExecTests(unittest.TestCase):
    def _npm_project(self, root: Path) -> None:
        (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
        (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")

    def test_native_exec_plan_uses_authoritative_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            plan = plan_native_exec(discover(root), ["view", "react", "version"])
            self.assertEqual(plan.manager, "npm")
            self.assertEqual(plan.argv, ("npm", "view", "react", "version"))
            self.assertEqual(plan.cwd, root)

    def test_pip_exec_uses_python_module_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            plan = plan_native_exec(discover(root), ["list", "--format=json"])
            self.assertEqual(plan.argv[:3], ("python", "-m", "pip"))

    def test_native_exec_refuses_ambiguous_manager_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            (root / "yarn.lock").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(NativeExecError, "multiple native lockfiles"):
                plan_native_exec(discover(root), ["version"])

    def test_execute_uses_exact_resolved_binary_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            plan = plan_native_exec(discover(root), ["view", "react"])
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "ok\n", "")

            result = execute_native_exec(plan, root, run=run, which=lambda _name: "/tools/npm")
            self.assertEqual(calls[0][0], "/tools/npm")
            self.assertEqual(result.stdout, "ok\n")
            self.assertIsNotNone(result.verification)

    def test_cli_exec_is_preview_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._npm_project(root)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["exec", "--path", str(root), "--", "view", "react"])
            self.assertEqual(code, 0)
            self.assertIn("npm view react", output.getvalue())
            self.assertIn("Preview only", output.getvalue())


class StatusTests(unittest.TestCase):
    def test_status_combines_health_snapshot_and_verification_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n', encoding="utf-8")
            (root / "Cargo.lock").write_text('version = 4\n', encoding="utf-8")
            data = project_status(discover(root))
            self.assertEqual(data["summary"]["components"], 1)
            self.assertEqual(data["summary"]["ecosystems"], ["rust"])
            self.assertFalse(data["integrity_snapshot"]["exists"])
            self.assertEqual(data["native_verification"]["coverage"]["planned_components"], 1)
            self.assertIsNone(data["storage"])
            self.assertTrue(data["policy"]["passed"])

    def test_status_storage_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            node_modules = root / "node_modules" / "foo"
            node_modules.mkdir(parents=True)
            (node_modules / "payload").write_bytes(b"x" * 1024)
            without = project_status(discover(root))
            with_storage = project_status(discover(root), include_storage=True)
            self.assertIsNone(without["storage"])
            self.assertGreaterEqual(with_storage["storage"]["summary"]["bytes"], 1024)

    def test_status_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["status", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertIn(code, (0, 1))
            self.assertEqual(data["summary"]["ecosystems"], ["go"])
            self.assertEqual(data["native_verification"]["coverage"]["planned_components"], 1)

    def test_status_fails_configured_policy_violation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            (root / "upm.toml").write_text('[policy]\ndenied_managers=["npm"]\n', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["status", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(data["policy"]["passed"])


class PolicyCliTests(unittest.TestCase):
    def test_policy_cli_json_reports_violation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (root / "upm.toml").write_text("[policy]\nrequire_lockfiles=true\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["policy", str(root), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(data["passed"])
            self.assertEqual(data["violations"][0]["code"], "policy.lockfile-required")

    def test_policy_cli_passes_without_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "go.mod").write_text("module example.com/app\ngo 1.24\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["policy", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("Policy: passed", output.getvalue())


class FleetPolicyCliTests(unittest.TestCase):
    def test_projects_policy_cli_json(self) -> None:
        from unified_project_manager.registry import register_project

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "projects.json"
            project = root / "app"
            project.mkdir()
            (project / "package.json").write_text('{"packageManager":"npm@11"}', encoding="utf-8")
            (project / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{}}}', encoding="utf-8")
            (project / "upm.toml").write_text('[policy]\ndenied_managers=["npm"]\n', encoding="utf-8")
            register_project(project, registry)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["projects", "policy", "--registry", str(registry), "--json"])
            data = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(data["summary"]["failed"], 1)
            self.assertFalse(data["projects"][0]["passed"])


if __name__ == "__main__":
    unittest.main()
