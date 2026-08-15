from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    GoSymbolReachabilityError,
    build_govulncheck_symbol_plan,
    parse_govulncheck_symbol_stream,
    validate_govulncheck_telemetry_mode,
)


class GoSymbolReachabilityTests(unittest.TestCase):
    def _config(self) -> dict:
        return {
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "scanner_name": "govulncheck",
                "scanner_version": "v1.6.0",
                "db": "file:///tmp/vulndb",
                "go_version": "go1.24.0",
                "scan_level": "symbol",
                "scan_mode": "source",
            }
        }

    def _sbom(self) -> dict:
        return {
            "SBOM": {
                "go_version": "go1.24.0",
                "modules": [
                    {"path": "example.com/dep", "version": "v1.2.3"},
                    {"path": "example.com/app"},
                ],
                "roots": ["example.com/app", "example.com/app/cmd"],
            }
        }

    def _stream(self) -> str:
        messages = [
            self._config(),
            self._sbom(),
            {
                "finding": {
                    "osv": "GO-2026-0001",
                    "trace": [{"module": "example.com/dep", "version": "v1.2.3"}],
                }
            },
            {
                "finding": {
                    "osv": "GO-2026-0001",
                    "trace": [{
                        "module": "example.com/dep",
                        "version": "v1.2.3",
                        "package": "example.com/dep/pkg",
                    }],
                }
            },
            {
                "finding": {
                    "osv": "GO-2026-0001",
                    "fixed_version": "v1.2.4",
                    "trace": [
                        {
                            "module": "example.com/dep",
                            "version": "v1.2.3",
                            "package": "example.com/dep/pkg",
                            "function": "Danger",
                            "receiver": "*Thing",
                            "position": {"filename": "pkg/danger.go", "line": 17, "column": 3},
                        },
                        {
                            "module": "example.com/app",
                            "package": "example.com/app",
                            "function": "main",
                            "position": {"filename": "main.go", "line": 9, "column": 2},
                        },
                    ],
                }
            },
            {
                "osv": {
                    "id": "GO-2026-0001",
                    "aliases": ["CVE-2026-1234", "GHSA-test-0001"],
                }
            },
        ]
        return "\n".join(json.dumps(message) for message in messages)

    def test_parser_preserves_scan_sbom_and_finding_levels(self) -> None:
        report = parse_govulncheck_symbol_stream(self._stream())

        self.assertEqual(report.config.protocol_version, GOVULNCHECK_PROTOCOL_VERSION)
        self.assertEqual(report.config.scan_mode, "source")
        self.assertEqual(report.config.scan_level, "symbol")
        self.assertTrue(report.config.database.startswith("file://"))
        self.assertIsNotNone(report.sbom)
        self.assertEqual(report.sbom.go_version, "go1.24.0")
        self.assertEqual(report.sbom.roots, ("example.com/app", "example.com/app/cmd"))
        self.assertTrue(report.sbom.has_module("example.com/dep", "v1.2.3"))
        self.assertFalse(report.sbom.has_module("example.com/dep", "v9.9.9"))
        self.assertEqual(
            [(module.path, module.version) for module in report.sbom.modules],
            [("example.com/app", None), ("example.com/dep", "v1.2.3")],
        )
        self.assertEqual([finding.level for finding in report.findings], ["module", "package", "symbol"])
        self.assertEqual(len(report.symbol_findings), 1)
        finding = report.symbol_findings[0]
        self.assertEqual(finding.osv, "GO-2026-0001")
        self.assertEqual(finding.vulnerable_frame.symbol, "*Thing.Danger")
        self.assertEqual(finding.trace[0].position["line"], 17)
        self.assertTrue(report.matches_advisory("GO-2026-0001", "CVE-2026-1234"))
        self.assertTrue(report.matches_advisory("GO-2026-0001", "GO-2026-0001"))
        self.assertFalse(report.matches_advisory("GO-2026-0001", "CVE-2026-9999"))
        self.assertEqual(report.to_dict()["sbom"]["roots"], ["example.com/app", "example.com/app/cmd"])

    def test_osv_message_may_follow_finding(self) -> None:
        report = parse_govulncheck_symbol_stream(self._stream())
        self.assertEqual(
            report.advisory_ids("GO-2026-0001"),
            ("CVE-2026-1234", "GHSA-test-0001", "GO-2026-0001"),
        )

    def test_parser_requires_exactly_one_valid_source_scan_sbom(self) -> None:
        missing = json.dumps(self._config())
        with self.assertRaisesRegex(GoSymbolReachabilityError, "missing its scan SBOM"):
            parse_govulncheck_symbol_stream(missing)

        duplicate = "\n".join(json.dumps(message) for message in [
            self._config(), self._sbom(), self._sbom(),
        ])
        with self.assertRaisesRegex(GoSymbolReachabilityError, "more than one SBOM"):
            parse_govulncheck_symbol_stream(duplicate)

        no_roots = self._sbom()
        no_roots["SBOM"]["roots"] = []
        with self.assertRaisesRegex(GoSymbolReachabilityError, "no root packages"):
            parse_govulncheck_symbol_stream("\n".join(
                json.dumps(message) for message in [self._config(), no_roots]
            ))

        invalid_module = self._sbom()
        invalid_module["SBOM"]["modules"] = [{"version": "v1.2.3"}]
        with self.assertRaisesRegex(GoSymbolReachabilityError, "missing path identity"):
            parse_govulncheck_symbol_stream("\n".join(
                json.dumps(message) for message in [self._config(), invalid_module]
            ))

        invalid_roots = self._sbom()
        invalid_roots["SBOM"]["roots"] = ["example.com/app", 7]
        with self.assertRaisesRegex(GoSymbolReachabilityError, "roots"):
            parse_govulncheck_symbol_stream("\n".join(
                json.dumps(message) for message in [self._config(), invalid_roots]
            ))

    def test_parser_rejects_wrong_or_missing_scan_semantics(self) -> None:
        wrong_protocol = json.dumps({
            "config": {
                "protocol_version": "v9.0.0",
                "db": "file:///tmp/vulndb",
                "scan_level": "symbol",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "protocol version"):
            parse_govulncheck_symbol_stream(wrong_protocol)

        package_scan = json.dumps({
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "db": "file:///tmp/vulndb",
                "scan_level": "package",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "symbol-level"):
            parse_govulncheck_symbol_stream(package_scan)

        missing_level = json.dumps({
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "db": "file:///tmp/vulndb",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "symbol-level"):
            parse_govulncheck_symbol_stream(missing_level)

        missing_mode = json.dumps({
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "db": "file:///tmp/vulndb",
                "scan_level": "symbol",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "source-mode"):
            parse_govulncheck_symbol_stream(missing_mode)

    def test_parser_rejects_nonlocal_database_and_ambiguous_message_shapes(self) -> None:
        remote = json.dumps({
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "db": "https://vuln.go.dev",
                "scan_level": "symbol",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "local file database"):
            parse_govulncheck_symbol_stream(remote)

        stream = "\n".join([
            json.dumps(self._config()),
            json.dumps({"progress": {"message": "x"}, "finding": {"osv": "GO-1", "trace": []}}),
        ])
        with self.assertRaisesRegex(GoSymbolReachabilityError, "exactly one"):
            parse_govulncheck_symbol_stream(stream)

    def test_offline_plan_requires_local_database_and_sets_all_network_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            database = root / "vulndb"
            project.mkdir()
            database.mkdir()

            plan = build_govulncheck_symbol_plan(project, database, executable="/tools/govulncheck")

            self.assertEqual(plan.cwd, project.resolve())
            self.assertEqual(plan.database, database.resolve())
            self.assertEqual(plan.database_uri, database.resolve().as_uri())
            self.assertEqual(plan.argv[0], "/tools/govulncheck")
            self.assertIn("symbol", plan.argv)
            self.assertIn("source", plan.argv)
            self.assertIn(database.resolve().as_uri(), plan.argv)
            self.assertEqual(plan.environment["GOPROXY"], "off")
            self.assertEqual(plan.environment["GOWORK"], "off")
            self.assertEqual(plan.environment["GOSUMDB"], "off")
            self.assertEqual(plan.environment["GOTOOLCHAIN"], "local")
            self.assertEqual(plan.telemetry_mode_required, "off")
            self.assertEqual(plan.to_dict()["project_mutation"], "not-planned")

    def test_plan_and_telemetry_preflight_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            missing_db = root / "missing"
            with self.assertRaisesRegex(GoSymbolReachabilityError, "database"):
                build_govulncheck_symbol_plan(project, missing_db)

        validate_govulncheck_telemetry_mode("off")
        for mode in ("local", "on", "", "unknown"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(GoSymbolReachabilityError, "telemetry mode 'off'"):
                    validate_govulncheck_telemetry_mode(mode)


if __name__ == "__main__":
    unittest.main()
