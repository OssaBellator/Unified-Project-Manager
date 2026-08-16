from __future__ import annotations

import os
import unittest

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

    def test_preserves_existing_path_key_casing_without_duplicates(self) -> None:
        environment = environment_with_preflight_go_path(
            {"Path": "first", "PATH": "duplicate"},
            "/tools/go",
        )
        path_keys = [key for key in environment if key.upper() == "PATH"]
        self.assertEqual(path_keys, ["Path"])
        self.assertEqual(environment["Path"], "/tools" + os.pathsep + "first")

    def test_refuses_unqualified_go_executable(self) -> None:
        with self.assertRaisesRegex(GoSymbolToolchainPathError, "no directory component"):
            environment_with_preflight_go_path({"PATH": "/ambient/bin"}, "go")


if __name__ == "__main__":
    unittest.main()
