from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.go_symbol_preflight import preflight_govulncheck_symbol
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan


class GoSymbolPreflightTests(unittest.TestCase):
    def _plan(self, root: Path):
        project = root / "project"
        database = root / "vulndb"
        project.mkdir()
        database.mkdir()
        return build_govulncheck_symbol_plan(
            project,
            database,
            executable="/tools/govulncheck",
        )

    def _which(self, name: str) -> str | None:
        if name == "go":
            return "/tools/go"
        if name == "/tools/govulncheck":
            return "/tools/govulncheck"
        return None

    def test_ready_preflight_inspects_telemetry_without_launching_govulncheck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "off\n", "")

            result = preflight_govulncheck_symbol(plan, run=run, which=self._which)

            self.assertTrue(result.ready)
            self.assertEqual(result.telemetry_mode, "off")
            self.assertEqual(result.go_executable, "/tools/go")
            self.assertEqual(result.govulncheck_executable, "/tools/govulncheck")
            self.assertEqual(len(calls), 1)
            argv, kwargs = calls[0]
            self.assertEqual(argv, ["/tools/go", "env", "GOTELEMETRY"])
            self.assertEqual(kwargs["cwd"], plan.cwd)
            self.assertEqual(kwargs["env"]["GOPROXY"], "off")
            self.assertEqual(kwargs["env"]["GOWORK"], "off")
            self.assertEqual(kwargs["env"]["GOSUMDB"], "off")
            self.assertEqual(kwargs["env"]["GOTOOLCHAIN"], "local")
            data = result.to_dict()
            self.assertFalse(data["executes_govulncheck"])
            self.assertFalse(data["mutates_telemetry_configuration"])
            self.assertEqual(data["project_mutation"], "none")

    def test_non_off_telemetry_fails_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = preflight_govulncheck_symbol(
                plan,
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "local\n", ""),
                which=self._which,
            )

            self.assertFalse(result.ready)
            self.assertEqual(result.telemetry_mode, "local")
            self.assertEqual(len(result.reasons), 1)
            self.assertIn("must already be 'off'", result.reasons[0])
            self.assertIn("will not change telemetry", result.reasons[0])

    def test_missing_executables_are_explicit_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = preflight_govulncheck_symbol(
                plan,
                run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("go env must not run without a Go executable")
                ),
                which=lambda _name: None,
            )

            self.assertFalse(result.ready)
            self.assertIsNone(result.go_executable)
            self.assertIsNone(result.govulncheck_executable)
            self.assertTrue(any("Go executable" in reason for reason in result.reasons))
            self.assertTrue(any("govulncheck executable" in reason for reason in result.reasons))

    def test_failed_telemetry_query_is_not_treated_as_off(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            result = preflight_govulncheck_symbol(
                plan,
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 2, "", "unsupported env key"),
                which=self._which,
            )

            self.assertFalse(result.ready)
            self.assertIsNone(result.telemetry_mode)
            self.assertTrue(any("could not inspect Go telemetry" in reason for reason in result.reasons))

    def test_stale_project_and_database_are_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            shutil.rmtree(plan.cwd)
            shutil.rmtree(plan.database)

            result = preflight_govulncheck_symbol(
                plan,
                run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("go env must not run for a missing project")
                ),
                which=self._which,
            )

            self.assertFalse(result.ready)
            self.assertTrue(any("project directory" in reason for reason in result.reasons))
            self.assertTrue(any("vulnerability database" in reason for reason in result.reasons))

    def test_go_env_oserror_is_an_explicit_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))

            def run(*_args, **_kwargs):
                raise OSError("exec format error")

            result = preflight_govulncheck_symbol(plan, run=run, which=self._which)
            self.assertFalse(result.ready)
            self.assertTrue(any("exec format error" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
