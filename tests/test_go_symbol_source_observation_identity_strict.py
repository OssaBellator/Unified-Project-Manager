from __future__ import annotations

import json
import unittest

from support_platform_paths import platform_absolute_fixture
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolSourceObservationError,
    parse_go_symbol_package_inputs,
)


class GoSymbolSourceObservationIdentityStrictTests(unittest.TestCase):
    def test_name_must_be_nonempty_string_when_present(self) -> None:
        for malformed in (0, False, [], {}, ""):
            with self.subTest(malformed=malformed):
                record = {
                    "Dir": platform_absolute_fixture("app"),
                    "ImportPath": "example.com/app",
                    "Name": malformed,
                    "GoFiles": ["main.go"],
                }
                with self.assertRaisesRegex(GoSymbolSourceObservationError, "field Name"):
                    parse_go_symbol_package_inputs(json.dumps(record))

    def test_package_directory_must_be_absolute(self) -> None:
        record = {
            "Dir": "relative/pkg",
            "ImportPath": "example.com/app",
            "Name": "main",
            "GoFiles": ["main.go"],
        }
        with self.assertRaisesRegex(GoSymbolSourceObservationError, "Dir is not an absolute path"):
            parse_go_symbol_package_inputs(json.dumps(record))

    def test_absolute_package_directory_is_retained_canonically(self) -> None:
        record = {
            "Dir": platform_absolute_fixture("app"),
            "ImportPath": "example.com/app",
            "Name": "main",
            "GoFiles": ["main.go"],
        }
        package = parse_go_symbol_package_inputs(json.dumps(record))[0]
        self.assertEqual(package.name, "main")
        self.assertEqual(package.directory, platform_absolute_fixture("app"))


if __name__ == "__main__":
    unittest.main()
