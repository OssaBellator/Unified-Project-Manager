from __future__ import annotations

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
        return build_govulncheck_symbol_plan(project, database, executable="govulncheck")

    def _which(self, name: str) -> str | None:
        if name == "go":
            return str(Path("tools/go").resolve())
        if name == "govulncheck":
            return str(Path("tools/govulncheck").resolve())
        return None

    def test_ready_preflight_inspects_telemetry_without_launching_govulncheck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "off\n", "")

            result = preflight_govulncheck_symbol(plan, run=run, which=self._which)

            self.assertTrue(result.ready)
            self.assertEqual(result.go_executable, self._which("go"))
            self.assertEqual(result.govulncheck_executable, self._which("govulncheck"))
            self.assertEqual(result.telemetry_mode, "off")
            self.assertEqual(result.reasons, ())
            self.assertEqual(len(calls), 1)
            argv, kwargs = calls[0]
            self.assertEqual(argv, [self._which("go"), "env", "GOTELEMETRY"])
            self.assertEqual(kwargs["cwd"], plan.cwd)
            self.assertEqual(kwargs["env"]["GOPROXY"], "off")
            self.assertEqual(kwargs["env"]["GOWORK"], "off")
            self.assertEqual(kwargs["env"]["GOSUMDB"], "off")
            self.assertEqual(kwargs["env"]["GOTOOLCHAIN"], "local")
            data = result.to_dict()
            self.assertFalse(data["executes_govulncheck"])
            self.assertFalse(data["mutates_telemetry_configuration"])
            self.assertEqual(data["network"], "none")

    def test_relative_executable_results_are_pinned_before_project_cwd_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            calls = []

            def which(name: str) -> str | None:
                if name == "go":
                    return str(Path("relative-tools/go"))
                if name == "govulncheck":
                    return str(Path("relative-tools/govulncheck"))
                return None

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, "off\n", "")

            result = preflight_govulncheck_symbol(plan, run=run, which=which)

            self.assertTrue(result.ready, result.reasons)
            self.assertTrue(Path(result.go_executable).is_absolute())
            self.assertTrue(Path(result.govulncheck_executable).is_absolute())
            self.assertEqual(calls[0][0][0], result.go_executable)
            self.assertNotEqual(Path(result.go_executable).parent, plan.cwd / "relative-tools")

    def test_non_off_telemetry_fails_without_changing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "local\n", "")

            result = preflight_govulncheck_symbol(plan, run=run, which=self._which)

            self.assertFalse(result.ready)
            self.assertEqual(result.telemetry_mode, "local")
            self.assertTrue(any("must already be 'off'" in reason for reason in result.reasons))
            self.assertEqual(calls, [[self._which("go"), "env", "GOTELEMETRY"]])

    def test_failed_telemetry_query_is_not_treated_as_off(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))

            result = preflight_govulncheck_symbol(
                plan,
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 2, "", "go env failed"),
                which=self._which,
            )

            self.assertFalse(result.ready)
            self.assertIsNone(result.telemetry_mode)
            self.assertTrue(any("could not inspect Go telemetry mode" in reason for reason in result.reasons))

    def test_go_env_oserror_is_an_explicit_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))

            def run(*_args, **_kwargs):
                raise OSError("cannot execute go")

            result = preflight_govulncheck_symbol(plan, run=run, which=self._which)
            self.assertFalse(result.ready)
            self.assertTrue(any("cannot execute go" in reason for reason in result.reasons))

    def test_missing_executables_are_explicit_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self._plan(Path(temporary))
            calls = []

            result = preflight_govulncheck_symbol(
                plan,
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
                which=lambda _name: None,
            )

            self.assertFalse(result.ready)
            self.assertTrue(any("Go executable" in reason for reason in result.reasons))
            self.assertTrue(any("govulncheck executable" in reason for reason in result.reasons))
            self.assertEqual(calls, [])

    def test_stale_project_and_database_are_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan.database.rmdir()

            result = preflight_govulncheck_symbol(
                plan,
                run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "off\n", ""),
                which=self._which,
            )
            self.assertFalse(result.ready)
            self.assertTrue(any("database is unavailable" in reason for reason in result.reasons))

            plan.database.mkdir()
            plan.cwd.rmdir()
            calls = []
            result = preflight_govulncheck_symbol(
                plan,
                run=lambda *args, **kwargs: calls.append((args, kwargs)),
                which=self._which,
            )
            self.assertFalse(result.ready)
            self.assertTrue(any("project directory is unavailable" in reason for reason in result.reasons))
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
