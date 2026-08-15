from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unified_project_manager.environment_entrypoint import main
from unified_project_manager.environment_inspection import (
    EnvironmentFinding,
    EnvironmentInspection,
    EnvironmentObservation,
)


class EnvironmentEntrypointTests(unittest.TestCase):
    def _project(self, root: Path) -> None:
        (root / "pyproject.toml").write_text('[project]\nname="app"\n', encoding="utf-8")

    def _json(self, argv: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv)
        return code, json.loads(output.getvalue())

    def test_json_output_is_local_and_does_not_dump_unrelated_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inspection = EnvironmentInspection(
                observations=(
                    EnvironmentObservation(
                        "VIRTUAL_ENV", "python-environment", "/outside/venv", "/outside/venv", False
                    ),
                ),
                findings=(
                    EnvironmentFinding(
                        "environment.python.external-virtualenv",
                        "warning",
                        "external environment",
                        "VIRTUAL_ENV",
                        "/outside/venv",
                    ),
                ),
            )
            with patch(
                "unified_project_manager.environment_entrypoint.inspect_environment",
                return_value=inspection,
            ):
                code, data = self._json([str(root), "--json"])

            self.assertEqual(code, 0)
            self.assertFalse(data["network_executed"])
            self.assertFalse(data["mutation_executed"])
            self.assertEqual(data["summary"]["warnings"], 1)
            self.assertEqual(
                {item["variable"] for item in data["observations"]},
                {"VIRTUAL_ENV"},
            )

    def test_strict_mode_fails_on_leakage_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            inspection = EnvironmentInspection(
                observations=(),
                findings=(
                    EnvironmentFinding(
                        "environment.python.external-pythonpath",
                        "warning",
                        "external import path",
                        "PYTHONPATH",
                        "/outside/src",
                    ),
                ),
            )
            with patch(
                "unified_project_manager.environment_entrypoint.inspect_environment",
                return_value=inspection,
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 1)
            self.assertTrue(data["summary"]["strict_failed"])

    def test_strict_mode_succeeds_without_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._project(root)
            with patch(
                "unified_project_manager.environment_entrypoint.inspect_environment",
                return_value=EnvironmentInspection((), ()),
            ):
                code, data = self._json([str(root), "--strict", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(data["summary"]["warnings"], 0)
            self.assertFalse(data["summary"]["strict_failed"])


if __name__ == "__main__":
    unittest.main()
