from __future__ import annotations

import json
import unittest

from support_platform_paths import platform_absolute_fixture
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolSourceObservationError,
    parse_go_symbol_build_environment,
    parse_go_symbol_package_inputs,
)


class GoSymbolSourceObservationProtocolStrictTests(unittest.TestCase):
    def test_optional_build_environment_values_must_be_strings(self) -> None:
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "CGO_ENABLED"):
            parse_go_symbol_build_environment(json.dumps({
                "GOOS": "linux",
                "GOARCH": "amd64",
                "GOVERSION": "go1.24.0",
                "CGO_ENABLED": 1,
            }))

    def test_go_list_boolean_fields_are_not_coerced(self) -> None:
        for field in ("Incomplete", "Standard", "DepOnly"):
            with self.subTest(field=field):
                record = {
                    "Dir": platform_absolute_fixture("app"),
                    "ImportPath": "example.com/app",
                    "GoFiles": ["main.go"],
                    field: 0,
                }
                with self.assertRaisesRegex(GoSymbolSourceObservationError, "not a boolean"):
                    parse_go_symbol_package_inputs(json.dumps(record))

        module = {
            "Dir": platform_absolute_fixture("app"),
            "ImportPath": "example.com/app",
            "GoFiles": ["main.go"],
            "Module": {"Path": "example.com/app", "Main": "false"},
        }
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "Module.Main"):
            parse_go_symbol_package_inputs(json.dumps(module))

    def test_module_versions_must_be_nonempty_strings_when_present(self) -> None:
        for module in (
            {"Path": "example.com/dep", "Version": 123},
            {"Path": "example.com/dep", "Version": ""},
            {"Path": "example.com/dep", "Replace": {"Path": "example.com/fork", "Version": 123}},
            {"Path": "example.com/dep", "Replace": {"Path": "example.com/fork", "Version": ""}},
        ):
            with self.subTest(module=module):
                record = {
                    "Dir": platform_absolute_fixture("app"),
                    "ImportPath": "example.com/app",
                    "GoFiles": ["main.go"],
                    "Module": module,
                }
                with self.assertRaisesRegex(GoSymbolSourceObservationError, "Version"):
                    parse_go_symbol_package_inputs(json.dumps(record))

    def test_deps_errors_shape_is_strict_even_when_falsey(self) -> None:
        for malformed in ({}, "", 0, False):
            with self.subTest(malformed=malformed):
                record = {
                    "Dir": platform_absolute_fixture("app"),
                    "ImportPath": "example.com/app",
                    "GoFiles": ["main.go"],
                    "DepsErrors": malformed,
                }
                with self.assertRaisesRegex(GoSymbolSourceObservationError, "DepsErrors is not an array"):
                    parse_go_symbol_package_inputs(json.dumps(record))


if __name__ == "__main__":
    unittest.main()
