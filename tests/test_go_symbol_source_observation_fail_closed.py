from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from support_platform_paths import platform_absolute_fixture
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolSourceObservationError,
    build_go_symbol_source_observation_plan,
    execute_go_symbol_source_observation,
    parse_go_symbol_package_inputs,
)


class GoSymbolSourceObservationFailClosedTests(unittest.TestCase):
    def test_empty_package_stream_is_refused(self) -> None:
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "no package records"):
            parse_go_symbol_package_inputs("")

    def test_dependency_only_stream_is_refused_as_rootless(self) -> None:
        payload = json.dumps({
            "Dir": platform_absolute_fixture("dep"),
            "ImportPath": "example.com/dep",
            "DepOnly": True,
            "Module": {"Path": "example.com/dep", "Version": "v1.2.3"},
            "GoFiles": ["dep.go"],
        })
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "no root package"):
            parse_go_symbol_package_inputs(payload)

    def test_duplicate_import_path_is_refused(self) -> None:
        payload = "\n".join([
            json.dumps({
                "Dir": platform_absolute_fixture("app-a"),
                "ImportPath": "example.com/app",
                "GoFiles": ["main.go"],
            }),
            json.dumps({
                "Dir": platform_absolute_fixture("app-b"),
                "ImportPath": "example.com/app",
                "GoFiles": ["main.go"],
            }),
        ])
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "duplicate ImportPath"):
            parse_go_symbol_package_inputs(payload)

    def test_zero_exit_rootless_loader_output_preserves_warning_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = build_go_symbol_source_observation_plan(Path(temporary))
            calls = 0

            def run(argv, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return subprocess.CompletedProcess(
                        argv,
                        0,
                        json.dumps({
                            "GOOS": "linux",
                            "GOARCH": "amd64",
                            "GOVERSION": "go1.24.0",
                        }),
                        "",
                    )
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "",
                    "warning: ./... matched no packages",
                )

            result = execute_go_symbol_source_observation(
                plan,
                run=run,
                which=lambda _name: "/tools/go",
            )

            self.assertFalse(result.succeeded)
            self.assertEqual(result.returncode, 1)
            self.assertIn("no package records", result.error or "")
            self.assertEqual(result.stderr, "warning: ./... matched no packages")
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
