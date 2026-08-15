from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from unified_project_manager.go_symbol_build_selection import (
    GoSymbolBuildSelectionError,
    compare_go_symbol_build_selection,
    govulncheck_build_selection,
    source_observation_build_selection,
)
from unified_project_manager.go_symbol_reachability import build_govulncheck_symbol_plan
from unified_project_manager.go_symbol_source_observation import (
    build_go_symbol_source_observation_plan,
)


class GoSymbolBuildSelectionTests(unittest.TestCase):
    def _plans(self, root: Path):
        project = root / "project"
        database = root / "vulndb"
        project.mkdir()
        database.mkdir()
        return (
            build_govulncheck_symbol_plan(project, database),
            build_go_symbol_source_observation_plan(project),
        )

    def test_current_default_plans_match_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            result = compare_go_symbol_build_selection(scanner, observation)

            self.assertTrue(result.matches)
            self.assertEqual(result.differences, ())
            self.assertEqual(result.govulncheck.patterns, ("./...",))
            self.assertEqual(result.govulncheck.tags, ())
            self.assertFalse(result.govulncheck.tests)
            self.assertEqual(result.govulncheck, result.source_observation)
            data = result.to_dict()
            self.assertEqual(data["scope"], "planned-go-symbol-build-selection-alignment")
            self.assertEqual(data["freshness"], "not-established")
            self.assertEqual(data["govulncheck_runtime_equivalence"], "not-established")

    def test_tag_order_is_normalized_but_tag_set_mismatch_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            scanner = replace(
                scanner,
                argv=(*scanner.argv[:-1], "-tags=linux,feature", scanner.argv[-1]),
            )
            observation = replace(
                observation,
                packages_argv=(
                    *observation.packages_argv[:-1],
                    "-tags", "feature,linux",
                    observation.packages_argv[-1],
                ),
            )
            self.assertTrue(compare_go_symbol_build_selection(scanner, observation).matches)

            observation = replace(
                observation,
                packages_argv=tuple(
                    item if item != "feature,linux" else "feature"
                    for item in observation.packages_argv
                ),
            )
            result = compare_go_symbol_build_selection(scanner, observation)
            self.assertFalse(result.matches)
            self.assertIn("build tags differ", result.differences)

    def test_test_inclusion_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            scanner = replace(scanner, argv=(*scanner.argv[:-1], "-test", scanner.argv[-1]))
            mismatch = compare_go_symbol_build_selection(scanner, observation)
            self.assertFalse(mismatch.matches)
            self.assertEqual(mismatch.differences, ("test inclusion differs",))

            observation = replace(
                observation,
                packages_argv=(*observation.packages_argv[:-1], "-test", observation.packages_argv[-1]),
            )
            self.assertTrue(compare_go_symbol_build_selection(scanner, observation).matches)

    def test_package_patterns_must_match_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            observation = replace(
                observation,
                packages_argv=(*observation.packages_argv[:-1], "./cmd/..."),
            )
            result = compare_go_symbol_build_selection(scanner, observation)
            self.assertFalse(result.matches)
            self.assertEqual(result.differences, ("package patterns differ",))

    def test_govulncheck_selection_requires_source_symbol_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, _observation = self._plans(Path(temporary))
            binary = replace(
                scanner,
                argv=tuple("binary" if item == "source" else item for item in scanner.argv),
            )
            with self.assertRaisesRegex(GoSymbolBuildSelectionError, "source mode"):
                govulncheck_build_selection(binary)

            package = replace(
                scanner,
                argv=tuple("package" if item == "symbol" else item for item in scanner.argv),
            )
            with self.assertRaisesRegex(GoSymbolBuildSelectionError, "symbol scan level"):
                govulncheck_build_selection(package)

    def test_boolean_test_flag_values_are_interpreted_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scanner, observation = self._plans(Path(temporary))
            scanner = replace(scanner, argv=(*scanner.argv[:-1], "-test=false", scanner.argv[-1]))
            self.assertFalse(govulncheck_build_selection(scanner).tests)

            bad = replace(
                observation,
                packages_argv=(*observation.packages_argv[:-1], "-test=maybe", observation.packages_argv[-1]),
            )
            with self.assertRaisesRegex(GoSymbolBuildSelectionError, "unsupported boolean"):
                source_observation_build_selection(bad)


if __name__ == "__main__":
    unittest.main()
