from __future__ import annotations

import unittest

from unified_project_manager.go_symbol_frame_source_alignment import (
    compare_positioned_govulncheck_frame_to_source_observation,
)
from unified_project_manager.go_symbol_reachability import GovulncheckFrame
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolBuildEnvironment,
    GoSymbolModuleInput,
    GoSymbolPackageInput,
    GoSymbolSourceObservation,
)


class GoSymbolFrameSourceAlignmentTests(unittest.TestCase):
    def _package(
        self,
        *,
        import_path: str = "example.com/dep/pkg",
        module_path: str = "example.com/dep",
        module_version: str | None = "v1.2.3",
        effective_path: str | None = None,
        effective_version: str | None = None,
        standard: bool = False,
        directory: str = "C:\\gomodcache\\example.com\\dep@v1.2.3\\pkg",
        compiled_go_files: tuple[str, ...] = ("dep.go",),
    ) -> GoSymbolPackageInput:
        module = None
        if not standard:
            module = GoSymbolModuleInput(
                path=module_path,
                version=module_version,
                main=False,
                effective_path=effective_path or module_path,
                effective_version=effective_version if effective_path is not None else module_version,
            )
        return GoSymbolPackageInput(
            import_path=import_path,
            name="pkg",
            standard=standard,
            dep_only=True,
            directory=directory,
            module=module,
            compiled_go_files=compiled_go_files,
            source_files=(("GoFiles", ("dep.go",)),),
            ignored_files=(),
            imports=(),
        )

    def _observation(self, *packages: GoSymbolPackageInput) -> GoSymbolSourceObservation:
        return GoSymbolSourceObservation(
            GoSymbolBuildEnvironment((
                ("GOOS", "windows"),
                ("GOARCH", "amd64"),
                ("GOVERSION", "go1.25.0"),
            )),
            tuple(packages or (self._package(),)),
        )

    def _frame(
        self,
        *,
        module: str = "example.com/dep",
        version: str | None = "v1.2.3",
        package: str | None = "example.com/dep/pkg",
        filename: str | None = "pkg/dep.go",
    ) -> GovulncheckFrame:
        position = None if filename is None else {"filename": filename, "line": 3, "column": 2}
        return GovulncheckFrame(
            module=module,
            version=version,
            package=package,
            function="Danger",
            receiver=None,
            position=position,
        )

    def test_positioned_frame_matches_observed_package_and_relative_syntax_file(self) -> None:
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(), self._observation()
        )
        self.assertTrue(alignment.matched, alignment.to_dict())
        self.assertEqual(alignment.normalized_scanner_filename, "pkg/dep.go")
        self.assertEqual(alignment.observed_syntax_file, "dep.go")
        data = alignment.to_dict()
        self.assertEqual(data["source_selection_equivalence"], "not-established")
        self.assertEqual(data["freshness"], "not-established")
        self.assertFalse(data["public"])
        self.assertFalse(data["persisted"])
        self.assertEqual(data["runtime_reachability"], "not-evaluated")
        self.assertEqual(data["exploitability"], "not-established")

    def test_package_mismatch_fails_closed(self) -> None:
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(package="example.com/dep/other"), self._observation()
        )
        self.assertFalse(alignment.matched)
        self.assertIn("absent", alignment.reason)

    def test_module_and_version_mismatch_fail_closed(self) -> None:
        wrong_module = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(module="example.com/other"), self._observation()
        )
        self.assertFalse(wrong_module.matched)
        self.assertIn("effective module", wrong_module.reason)

        wrong_version = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(version="v9.9.9"), self._observation()
        )
        self.assertFalse(wrong_version.matched)
        self.assertIn("module version", wrong_version.reason)

    def test_missing_or_unusable_position_is_explicit(self) -> None:
        absent = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(filename=None), self._observation()
        )
        self.assertFalse(absent.matched)
        self.assertIn("position", absent.reason)
        self.assertIn("absent", absent.reason)

        absolute = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(filename="C:\\tmp\\pkg\\dep.go"), self._observation()
        )
        self.assertFalse(absolute.matched)
        self.assertIn("module-relative", absolute.reason)

    def test_module_relative_path_escape_is_rejected(self) -> None:
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(filename="pkg/../dep.go"), self._observation()
        )
        self.assertFalse(alignment.matched)
        self.assertIn("escapes", alignment.reason)

    def test_path_separator_normalization_matches_protocol_path(self) -> None:
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(filename="pkg\\dep.go"), self._observation()
        )
        self.assertTrue(alignment.matched, alignment.to_dict())
        self.assertEqual(alignment.normalized_scanner_filename, "pkg/dep.go")

    def test_replacement_uses_effective_module_identity_but_logical_package_prefix(self) -> None:
        package = self._package(
            import_path="example.com/original/pkg",
            module_path="example.com/original",
            effective_path="example.com/fork",
            effective_version="v1.2.3-fixed",
        )
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(
                module="example.com/fork",
                version="v1.2.3-fixed",
                package="example.com/original/pkg",
            ),
            self._observation(package),
        )
        self.assertTrue(alignment.matched, alignment.to_dict())
        self.assertEqual(alignment.observed_module, "example.com/fork")

    def test_absolute_compiled_file_is_accepted_only_inside_observed_package_directory(self) -> None:
        inside = self._package(
            compiled_go_files=("C:\\gomodcache\\example.com\\dep@v1.2.3\\pkg\\dep.go",),
        )
        accepted = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(), self._observation(inside)
        )
        self.assertTrue(accepted.matched, accepted.to_dict())

        generated = self._package(
            compiled_go_files=("C:\\gocache\\generated\\dep.go",),
        )
        rejected = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(), self._observation(generated)
        )
        self.assertFalse(rejected.matched)
        self.assertIn("outside the observed package directory", rejected.reason)

    def test_standard_library_behavior_is_explicit_and_conservative(self) -> None:
        standard = self._package(
            import_path="fmt",
            standard=True,
            directory="C:\\Go\\src\\fmt",
            compiled_go_files=("print.go",),
        )
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(module="stdlib", version="go1.25.0", package="fmt", filename="print.go"),
            self._observation(standard),
        )
        self.assertFalse(alignment.matched)
        self.assertIn("standard-library", alignment.reason)

    def test_multiple_package_candidates_fail_closed_as_ambiguous(self) -> None:
        package = self._package()
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(), self._observation(package, package)
        )
        self.assertFalse(alignment.matched)
        self.assertIn("multiple observed packages", alignment.reason)

    def test_multiple_syntax_file_records_for_same_position_fail_closed_as_ambiguous(self) -> None:
        package = self._package(compiled_go_files=("dep.go", "./dep.go"))
        alignment = compare_positioned_govulncheck_frame_to_source_observation(
            self._frame(), self._observation(package)
        )
        self.assertFalse(alignment.matched)
        self.assertIn("multiple observed syntax-file records", alignment.reason)


if __name__ == "__main__":
    unittest.main()
