from __future__ import annotations

import unittest

from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    GoSymbolReachabilityError,
    GovulncheckConfig,
    GovulncheckModule,
    GovulncheckReport,
    GovulncheckSBOM,
)
from unified_project_manager.go_symbol_scan_alignment import (
    compare_go_symbol_observation_to_scan_sbom,
)
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolBuildEnvironment,
    GoSymbolModuleInput,
    GoSymbolPackageInput,
    GoSymbolSourceObservation,
)


class GoSymbolScanAlignmentTests(unittest.TestCase):
    def _observation(
        self,
        *,
        dep_effective_path="example.com/dep",
        dep_effective_version="v1.2.3",
        roots=("example.com/app",),
    ) -> GoSymbolSourceObservation:
        root_set = set(roots)
        packages = [
            GoSymbolPackageInput(
                import_path="example.com/app",
                name="main",
                standard=False,
                dep_only="example.com/app" not in root_set,
                directory="/tmp/app",
                module=GoSymbolModuleInput(
                    path="example.com/app",
                    version=None,
                    main=True,
                    effective_path="example.com/app",
                    effective_version=None,
                ),
                source_files=(("GoFiles", ("main.go",)),),
                ignored_files=(),
                imports=("example.com/dep/pkg",),
            ),
            GoSymbolPackageInput(
                import_path="example.com/dep/pkg",
                name="pkg",
                standard=False,
                dep_only="example.com/dep/pkg" not in root_set,
                directory="/tmp/dep/pkg",
                module=GoSymbolModuleInput(
                    path="example.com/original" if dep_effective_path != "example.com/dep" else "example.com/dep",
                    version="v1.2.3",
                    main=False,
                    effective_path=dep_effective_path,
                    effective_version=dep_effective_version,
                ),
                source_files=(("GoFiles", ("dep.go",)),),
                ignored_files=(),
                imports=(),
            ),
            GoSymbolPackageInput(
                import_path="fmt",
                name="fmt",
                standard=True,
                dep_only=True,
                directory="/go/src/fmt",
                module=None,
                source_files=(("GoFiles", ("print.go",)),),
                ignored_files=(),
                imports=(),
            ),
        ]
        return GoSymbolSourceObservation(
            GoSymbolBuildEnvironment((("GOOS", "linux"), ("GOARCH", "amd64"), ("GOVERSION", "go1.24.0"))),
            tuple(packages),
        )

    def _report(self, *, modules=None, roots=("example.com/app",), include_sbom=True):
        config = GovulncheckConfig(
            protocol_version=GOVULNCHECK_PROTOCOL_VERSION,
            scanner_name="govulncheck",
            scanner_version="v1.6.0",
            database="file:///tmp/vulndb",
            database_last_modified=None,
            go_version="go1.24.0",
            scan_level="symbol",
            scan_mode="source",
        )
        sbom = None
        if include_sbom:
            sbom = GovulncheckSBOM(
                go_version="go1.24.0",
                modules=tuple(modules or (
                    GovulncheckModule("example.com/app", None),
                    GovulncheckModule("example.com/dep", "v1.2.3"),
                )),
                roots=tuple(roots),
            )
        return GovulncheckReport(config, {}, (), sbom)

    def test_matching_roots_and_effective_module_build_list_are_declared_match(self) -> None:
        alignment = compare_go_symbol_observation_to_scan_sbom(
            self._observation(), self._report()
        )
        self.assertTrue(alignment.roots_match)
        self.assertTrue(alignment.modules_match)
        self.assertTrue(alignment.declared_inventory_match)
        self.assertEqual(alignment.observation_modules, (
            ("example.com/app", None),
            ("example.com/dep", "v1.2.3"),
        ))
        data = alignment.to_dict()
        self.assertEqual(data["freshness"], "not-established")
        self.assertEqual(data["source_selection_equivalence"], "not-established")
        self.assertEqual(data["build_configuration_equivalence"], "not-established")

    def test_root_mismatch_is_visible_without_changing_module_match(self) -> None:
        alignment = compare_go_symbol_observation_to_scan_sbom(
            self._observation(), self._report(roots=("example.com/app/cmd",))
        )
        self.assertFalse(alignment.roots_match)
        self.assertTrue(alignment.modules_match)
        self.assertFalse(alignment.declared_inventory_match)

    def test_module_or_version_mismatch_is_visible(self) -> None:
        wrong_module = compare_go_symbol_observation_to_scan_sbom(
            self._observation(),
            self._report(modules=(
                GovulncheckModule("example.com/app", None),
                GovulncheckModule("example.com/other", "v1.2.3"),
            )),
        )
        self.assertFalse(wrong_module.modules_match)
        self.assertFalse(wrong_module.declared_inventory_match)

        wrong_version = compare_go_symbol_observation_to_scan_sbom(
            self._observation(),
            self._report(modules=(
                GovulncheckModule("example.com/app", None),
                GovulncheckModule("example.com/dep", "v9.9.9"),
            )),
        )
        self.assertFalse(wrong_version.modules_match)

    def test_replacement_comparison_uses_effective_module_identity(self) -> None:
        observation = self._observation(
            dep_effective_path="example.com/fork",
            dep_effective_version="v1.2.3-fixed",
        )
        report = self._report(modules=(
            GovulncheckModule("example.com/app", None),
            GovulncheckModule("example.com/fork", "v1.2.3-fixed"),
        ))
        alignment = compare_go_symbol_observation_to_scan_sbom(observation, report)
        self.assertTrue(alignment.modules_match)
        self.assertNotIn(("example.com/original", "v1.2.3"), alignment.observation_modules)

    def test_standard_library_packages_do_not_become_module_inventory(self) -> None:
        alignment = compare_go_symbol_observation_to_scan_sbom(
            self._observation(), self._report()
        )
        self.assertNotIn(("fmt", None), alignment.observation_modules)
        self.assertTrue(alignment.modules_match)

    def test_missing_scan_sbom_is_refused(self) -> None:
        with self.assertRaisesRegex(GoSymbolReachabilityError, "without govulncheck scan SBOM"):
            compare_go_symbol_observation_to_scan_sbom(
                self._observation(), self._report(include_sbom=False)
            )


if __name__ == "__main__":
    unittest.main()
