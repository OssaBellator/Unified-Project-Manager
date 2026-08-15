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
    def _stream(self) -> str:
        messages = [
            {
                "config": {
                    "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                    "scanner_name": "govulncheck",
                    "scanner_version": "v1.6.0",
                    "db": "file:///tmp/vulndb",
                    "go_version": "go1.24.0",
                    "scan_level": "symbol",
                    "scan_mode": "source",
                }
            },
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
        # Streaming JSON is a sequence of objects, not necessarily one JSON array.
        return "\n".join(json.dumps(message) for message in messages)

    def test_parser_preserves_module_package_and_symbol_levels(self) -> None:
        report = parse_govulncheck_symbol_stream(self._stream())

        self.assertEqual(report.config.protocol_version, GOVULNCHECK_PROTOCOL_VERSION)
        self.assertEqual(report.config.scan_mode, "source")
        self.assertEqual(report.config.scan_level, "symbol")
        self.assertEqual([finding.level for finding in report.findings], ["module", "package", "symbol"])
        self.assertEqual(len(report.symbol_findings), 1)
        finding = report.symbol_findings[0]
        self.assertEqual(finding.osv, "GO-2026-0001")
        self.assertEqual(finding.vulnerable_frame.symbol, "*Thing.Danger")
        self.assertEqual(finding.trace[0].position["line"], 17)
        self.assertTrue(report.matches_advisory("GO-2026-0001", "CVE-2026-1234"))
        self.assertTrue(report.matches_advisory("GO-2026-0001", "GO-2026-0001"))
        self.assertFalse(report.matches_advisory("GO-2026-0001", "CVE-2026-9999"))

    def test_osv_message_may_follow_finding(self) -> None:
        report = parse_govulncheck_symbol_stream(self._stream())
        self.assertEqual(
            report.advisory_ids("GO-2026-0001"),
            ("CVE-2026-1234", "GHSA-test-0001", "GO-2026-0001"),
        )

    def test_parser_rejects_wrong_protocol_or_scan_semantics(self) -> None:
        wrong_protocol = json.dumps({
            "config": {
                "protocol_version": "v9.0.0",
                "scan_level": "symbol",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "protocol version"):
            parse_govulncheck_symbol_stream(wrong_protocol)

        package_scan = json.dumps({
            "config": {
                "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                "scan_level": "package",
                "scan_mode": "source",
            }
        })
        with self.assertRaisesRegex(GoSymbolReachabilityError, "symbol-level"):
            parse_govulncheck_symbol_stream(package_scan)

    def test_parser_rejects_ambiguous_message_shapes(self) -> None:
        stream = "\n".join([
            json.dumps({
                "config": {
                    "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                    "scan_level": "symbol",
                    "scan_mode": "source",
                }
            }),
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
            self.assertFalse(plan.to_dict()["project_mutation"] != "not-planned")

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
