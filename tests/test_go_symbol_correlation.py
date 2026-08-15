from __future__ import annotations

import unittest

from unified_project_manager.go_symbol_correlation import correlate_govulncheck_symbols
from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    GovulncheckConfig,
    GovulncheckFinding,
    GovulncheckFrame,
    GovulncheckModule,
    GovulncheckReport,
    GovulncheckSBOM,
)


class GoSymbolCorrelationTests(unittest.TestCase):
    def _report(
        self,
        *,
        osv: str = "GO-2026-0001",
        aliases: tuple[str, ...] = ("CVE-2026-1234",),
        module: str = "example.com/dep",
        version: str | None = "v1.2.3",
        package: str = "example.com/dep/pkg",
        function: str = "Danger",
        sbom_module: str | None = None,
        sbom_version: str | None = None,
        include_sbom: bool = True,
    ) -> GovulncheckReport:
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
        finding = GovulncheckFinding(
            osv=osv,
            fixed_version="v1.2.4",
            trace=(
                GovulncheckFrame(
                    module=module,
                    version=version,
                    package=package,
                    function=function,
                    receiver=None,
                    position={"filename": "pkg/danger.go", "line": 17},
                ),
                GovulncheckFrame(
                    module="example.com/app",
                    version=None,
                    package="example.com/app",
                    function="main",
                    receiver=None,
                    position={"filename": "main.go", "line": 8},
                ),
            ),
        )
        sbom = None
        if include_sbom:
            declared_module = sbom_module if sbom_module is not None else module
            declared_version = sbom_version if sbom_version is not None else version
            sbom = GovulncheckSBOM(
                go_version="go1.24.0",
                modules=(
                    GovulncheckModule("example.com/app", None),
                    GovulncheckModule(declared_module, declared_version),
                ),
                roots=("example.com/app",),
            )
        return GovulncheckReport(config, {osv: aliases}, (finding,), sbom)

    def _impact(
        self,
        *,
        advisory_id: str = "GO-2026-0001",
        component: str = ".:go",
        version: str = "v1.2.3",
        logical_module: str = "example.com/dep",
        effective_module: str = "example.com/dep",
        paths: list[list[str]] | None = None,
    ) -> dict:
        return {
            "advisory_id": advisory_id,
            "ecosystem": "Go",
            "package": effective_module,
            "version": version,
            "provider": "go-modules",
            "scope": "module-requirement",
            "component": component,
            "paths": paths or [["example.com/app", logical_module]],
            "evidence": {
                "module": logical_module,
                "effective_name": effective_module,
            },
        }

    def test_direct_identity_module_version_and_scan_sbom_match(self) -> None:
        result = correlate_govulncheck_symbols(
            self._report(), [self._impact()], component=".:go"
        )
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.unmatched, ())
        match = result.matches[0]
        self.assertEqual(match.advisory_id, "GO-2026-0001")
        self.assertEqual(match.advisory_identity, "direct")
        self.assertEqual(match.module, "example.com/dep")
        self.assertEqual(match.version, "v1.2.3")
        self.assertEqual(match.symbol, "Danger")
        self.assertEqual(match.dependency_paths, (("example.com/app", "example.com/dep"),))
        data = match.to_dict()
        self.assertEqual(data["correlation"], "scan-sbom+advisory+effective-module+exact-version")
        self.assertEqual(data["runtime_reachability"], "not-evaluated")
        self.assertEqual(data["exploitability"], "not-established")
        self.assertFalse(data["persisted"])

    def test_alias_match_still_requires_exact_module_and_version(self) -> None:
        result = correlate_govulncheck_symbols(
            self._report(),
            [self._impact(advisory_id="CVE-2026-1234")],
            component=".:go",
        )
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.matches[0].advisory_identity, "alias")

        wrong_module = correlate_govulncheck_symbols(
            self._report(module="example.com/other"),
            [self._impact(advisory_id="CVE-2026-1234")],
            component=".:go",
        )
        self.assertEqual(wrong_module.matches, ())
        self.assertIn("effective module", wrong_module.unmatched[0].reason)

        wrong_version = correlate_govulncheck_symbols(
            self._report(version="v9.9.9"),
            [self._impact(advisory_id="CVE-2026-1234")],
            component=".:go",
        )
        self.assertEqual(wrong_version.matches, ())
        self.assertIn("exact version", wrong_version.unmatched[0].reason)

    def test_replacement_correlates_against_effective_module_not_logical_module(self) -> None:
        impact = self._impact(
            advisory_id="CVE-2026-1234",
            version="v1.2.3-fixed",
            logical_module="example.com/original",
            effective_module="example.com/fork",
            paths=[["example.com/app", "example.com/original"]],
        )
        report = self._report(
            module="example.com/fork",
            version="v1.2.3-fixed",
            package="example.com/original/pkg",
        )
        result = correlate_govulncheck_symbols(report, [impact], component=".:go")

        self.assertEqual(len(result.matches), 1)
        match = result.matches[0]
        self.assertEqual(match.module, "example.com/fork")
        self.assertEqual(match.package, "example.com/original/pkg")
        self.assertEqual(
            match.dependency_paths,
            (("example.com/app", "example.com/original"),),
        )

        logical_report = self._report(
            module="example.com/original",
            version="v1.2.3-fixed",
            package="example.com/original/pkg",
        )
        refused = correlate_govulncheck_symbols(logical_report, [impact], component=".:go")
        self.assertEqual(refused.matches, ())
        self.assertIn("effective module", refused.unmatched[0].reason)

    def test_missing_finding_version_fails_closed(self) -> None:
        result = correlate_govulncheck_symbols(
            self._report(version=None), [self._impact()], component=".:go"
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(len(result.unmatched), 1)
        self.assertIn("missing module version", result.unmatched[0].reason)

    def test_missing_scan_sbom_fails_closed_even_when_upm_identity_matches(self) -> None:
        result = correlate_govulncheck_symbols(
            self._report(include_sbom=False), [self._impact()], component=".:go"
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(len(result.unmatched), 1)
        self.assertIn("missing scan SBOM", result.unmatched[0].reason)

    def test_scan_sbom_must_contain_finding_module_and_exact_version(self) -> None:
        wrong_module = correlate_govulncheck_symbols(
            self._report(sbom_module="example.com/other"),
            [self._impact()],
            component=".:go",
        )
        self.assertEqual(wrong_module.matches, ())
        self.assertIn("absent from the scan SBOM build list", wrong_module.unmatched[0].reason)

        wrong_version = correlate_govulncheck_symbols(
            self._report(sbom_version="v9.9.9"),
            [self._impact()],
            component=".:go",
        )
        self.assertEqual(wrong_version.matches, ())
        self.assertIn("absent from the scan SBOM build list", wrong_version.unmatched[0].reason)

    def test_component_scope_and_provider_filter_prevent_cross_attachment(self) -> None:
        impacts = [
            self._impact(component="packages/other:go"),
            {**self._impact(), "provider": "npm-lock-tree"},
        ]
        result = correlate_govulncheck_symbols(
            self._report(), impacts, component=".:go"
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(len(result.unmatched), 1)
        self.assertIn("advisory id/alias", result.unmatched[0].reason)

    def test_duplicate_exact_impacts_consolidate_dependency_paths(self) -> None:
        one = self._impact(paths=[["app", "left", "example.com/dep"]])
        two = self._impact(paths=[["app", "right", "example.com/dep"]])
        result = correlate_govulncheck_symbols(
            self._report(), [two, one], component=".:go"
        )
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(
            result.matches[0].dependency_paths,
            (
                ("app", "left", "example.com/dep"),
                ("app", "right", "example.com/dep"),
            ),
        )

    def test_multiple_alias_advisory_rows_are_refused_as_ambiguous(self) -> None:
        report = self._report(aliases=("CVE-2026-1234", "GHSA-test-0001"))
        impacts = [
            self._impact(advisory_id="CVE-2026-1234"),
            self._impact(advisory_id="GHSA-test-0001"),
        ]
        result = correlate_govulncheck_symbols(report, impacts, component=".:go")
        self.assertEqual(result.matches, ())
        self.assertEqual(len(result.unmatched), 1)
        self.assertIn("multiple UPM advisory identities", result.unmatched[0].reason)
        data = result.unmatched[0].to_dict()
        self.assertIsInstance(data["known_advisory_ids"], list)


if __name__ == "__main__":
    unittest.main()
