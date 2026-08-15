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
from unified_project_manager.go_symbol_scan_identity import (
    govulncheck_scan_declaration_identity,
)


class GoSymbolScanIdentityTests(unittest.TestCase):
    def _report(
        self,
        *,
        database="file:///tmp/vulndb",
        database_last_modified="2026-08-15T00:00:00Z",
        scanner_version="v1.6.0",
        scan_mode="source",
        scan_level="symbol",
        modules=None,
        roots=None,
        include_sbom=True,
    ):
        config = GovulncheckConfig(
            protocol_version=GOVULNCHECK_PROTOCOL_VERSION,
            scanner_name="govulncheck",
            scanner_version=scanner_version,
            database=database,
            database_last_modified=database_last_modified,
            go_version="go1.24.0",
            scan_level=scan_level,
            scan_mode=scan_mode,
        )
        sbom = None
        if include_sbom:
            sbom = GovulncheckSBOM(
                go_version="go1.24.0",
                modules=tuple(modules or (
                    GovulncheckModule("example.com/dep", "v1.2.3"),
                    GovulncheckModule("example.com/app", None),
                )),
                roots=tuple(roots or ("example.com/app/cmd", "example.com/app")),
            )
        return GovulncheckReport(config, {}, (), sbom)

    def test_identity_is_deterministic_across_module_and_root_order(self) -> None:
        one = govulncheck_scan_declaration_identity(self._report())
        two = govulncheck_scan_declaration_identity(self._report(
            modules=(
                GovulncheckModule("example.com/app", None),
                GovulncheckModule("example.com/dep", "v1.2.3"),
            ),
            roots=("example.com/app", "example.com/app/cmd", "example.com/app"),
        ))
        self.assertEqual(one.modules, two.modules)
        self.assertEqual(one.roots, two.roots)
        self.assertEqual(one.canonical_bytes(), two.canonical_bytes())
        self.assertEqual(one.sha256, two.sha256)
        self.assertEqual(len(one.sha256), 64)

    def test_identity_changes_when_scanner_database_scan_semantics_or_build_list_changes(self) -> None:
        base = govulncheck_scan_declaration_identity(self._report()).sha256
        database = govulncheck_scan_declaration_identity(
            self._report(database="file:///tmp/other-db")
        ).sha256
        scanner = govulncheck_scan_declaration_identity(
            self._report(scanner_version="v1.7.0")
        ).sha256
        mode = govulncheck_scan_declaration_identity(
            self._report(scan_mode="binary")
        ).sha256
        level = govulncheck_scan_declaration_identity(
            self._report(scan_level="package")
        ).sha256
        module = govulncheck_scan_declaration_identity(self._report(
            modules=(
                GovulncheckModule("example.com/app", None),
                GovulncheckModule("example.com/dep", "v1.2.4"),
            ),
        )).sha256
        roots = govulncheck_scan_declaration_identity(self._report(
            roots=("example.com/app/other",),
        )).sha256
        self.assertEqual(len({base, database, scanner, mode, level, module, roots}), 7)

    def test_identity_retains_database_scan_semantics_and_go_versions(self) -> None:
        identity = govulncheck_scan_declaration_identity(self._report())
        data = identity.to_dict()
        self.assertEqual(data["database_last_modified"], "2026-08-15T00:00:00Z")
        self.assertEqual(data["scan_mode"], "source")
        self.assertEqual(data["scan_level"], "symbol")
        self.assertEqual(data["config_go_version"], "go1.24.0")
        self.assertEqual(data["sbom_go_version"], "go1.24.0")
        self.assertEqual(data["scope"], "govulncheck-scan-declaration")

    def test_identity_explicitly_refuses_freshness_claims(self) -> None:
        data = govulncheck_scan_declaration_identity(self._report()).to_dict()
        self.assertEqual(data["freshness"], "not-established")
        self.assertFalse(data["source_state_fingerprint"])
        self.assertFalse(data["build_configuration_fingerprint"])
        self.assertIn("does not establish unchanged source", data["interpretation"])

    def test_missing_sbom_cannot_form_scan_declaration_identity(self) -> None:
        with self.assertRaisesRegex(GoSymbolReachabilityError, "without retained SBOM"):
            govulncheck_scan_declaration_identity(self._report(include_sbom=False))


if __name__ == "__main__":
    unittest.main()
