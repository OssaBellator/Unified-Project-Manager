from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from unified_project_manager.go_symbol_toolchain_path import (
    GoSymbolToolchainPathError,
    environment_with_preflight_go_path,
)


class GoSymbolToolchainPathTests(unittest.TestCase):
    def test_prefixes_resolved_go_directory_and_preserves_path(self) -> None:
        environment = environment_with_preflight_go_path(
            {"PATH": "/ambient/bin", "OTHER": "kept"},
            "/tools/go",
        )
        self.assertEqual(environment["PATH"], "/tools" + os.pathsep + "/ambient/bin")
        self.assertEqual(environment["OTHER"], "kept")

    def test_case_sensitive_environment_does_not_treat_mixed_case_path_as_path(self) -> None:
        with patch(
            "unified_project_manager.go_symbol_toolchain_path._ENVIRONMENT_KEYS_CASE_INSENSITIVE",
            False,
        ):
            environment = environment_with_preflight_go_path(
                {"Path": "unrelated"},
                "/tools/go",
            )
        self.assertEqual(environment["PATH"], "/tools")
        self.assertEqual(environment["Path"], "unrelated")

    def test_case_insensitive_environment_canonicalizes_path_without_duplicates(self) -> None:
        with patch(
            "unified_project_manager.go_symbol_toolchain_path._ENVIRONMENT_KEYS_CASE_INSENSITIVE",
            True,
        ):
            environment = environment_with_preflight_go_path(
                {"Path": "first", "PATH": "exact"},
                "/tools/go",
            )
        path_keys = [key for key in environment if key.upper() == "PATH"]
        self.assertEqual(path_keys, ["PATH"])
        self.assertEqual(environment["PATH"], "/tools" + os.pathsep + "exact")

    def test_refuses_relative_or_unqualified_go_executable(self) -> None:
        for executable in ("go", "tools/go"):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(GoSymbolToolchainPathError, "not absolute"):
                    environment_with_preflight_go_path({"PATH": "/ambient/bin"}, executable)


if __name__ == "__main__":
    unittest.main()
