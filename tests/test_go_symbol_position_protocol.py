from __future__ import annotations

import json
import unittest

from unified_project_manager.go_symbol_reachability import (
    GOVULNCHECK_PROTOCOL_VERSION,
    GoSymbolReachabilityError,
    parse_govulncheck_symbol_stream,
)


class GoSymbolPositionProtocolTests(unittest.TestCase):
    def _stream(self, position: object) -> str:
        messages = [
            {
                "config": {
                    "protocol_version": GOVULNCHECK_PROTOCOL_VERSION,
                    "scanner_name": "govulncheck",
                    "scanner_version": "v1.6.0",
                    "db": "file:///tmp/vulndb",
                    "go_version": "go1.25.0",
                    "scan_level": "symbol",
                    "scan_mode": "source",
                }
            },
            {
                "SBOM": {
                    "go_version": "go1.25.0",
                    "modules": [
                        {"path": "example.com/dep", "version": "v1.2.3"},
                    ],
                    "roots": ["example.com/app"],
                }
            },
            {
                "finding": {
                    "osv": "GO-2026-0001",
                    "trace": [
                        {
                            "module": "example.com/dep",
                            "version": "v1.2.3",
                            "package": "example.com/dep/pkg",
                            "function": "Danger",
                            "position": position,
                        }
                    ],
                }
            },
        ]
        return "\n".join(json.dumps(message) for message in messages)

    def _parsed_position(self, position: object):
        report = parse_govulncheck_symbol_stream(self._stream(position))
        return report.symbol_findings[0].vulnerable_frame.position

    def test_non_object_position_fails_closed(self) -> None:
        for value in ([], "position", 7, False):
            with self.subTest(value=value), self.assertRaisesRegex(
                GoSymbolReachabilityError, "not an object"
            ):
                self._parsed_position(value)

    def test_valid_position_preserves_complete_protocol_coordinates(self) -> None:
        value = {
            "filename": "pkg/dep.go",
            "offset": 18,
            "line": 3,
            "column": 6,
        }
        self.assertEqual(self._parsed_position(value), value)

    def test_position_requires_all_numeric_protocol_fields(self) -> None:
        complete = {"offset": 18, "line": 3, "column": 6}
        for missing in ("offset", "line", "column"):
            value = {key: item for key, item in complete.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(
                GoSymbolReachabilityError, missing
            ):
                self._parsed_position(value)

    def test_position_numeric_fields_fail_closed_on_wrong_types(self) -> None:
        complete = {"offset": 18, "line": 3, "column": 6}
        for name in ("offset", "line", "column"):
            for invalid in (False, "7", 1.5, None):
                value = {**complete, name: invalid}
                with self.subTest(name=name, invalid=invalid), self.assertRaisesRegex(
                    GoSymbolReachabilityError, name
                ):
                    self._parsed_position(value)

    def test_position_numeric_ranges_follow_go_token_validity(self) -> None:
        complete = {"offset": 18, "line": 3, "column": 6}
        for name, invalid in (
            ("offset", -1),
            ("line", 0),
            ("line", -1),
            ("column", -1),
        ):
            with self.subTest(name=name, invalid=invalid), self.assertRaisesRegex(
                GoSymbolReachabilityError, name
            ):
                self._parsed_position({**complete, name: invalid})

    def test_zero_column_is_valid_protocol_position_but_not_exact_byte_column(self) -> None:
        value = {"offset": 18, "line": 3, "column": 0}
        self.assertEqual(self._parsed_position(value), value)

    def test_filename_is_optional_but_present_value_must_be_nonempty_string(self) -> None:
        numeric = {"offset": 18, "line": 3, "column": 6}
        self.assertEqual(self._parsed_position(numeric), numeric)
        for filename in ("", None, 7, False):
            with self.subTest(filename=filename), self.assertRaisesRegex(
                GoSymbolReachabilityError, "filename"
            ):
                self._parsed_position({**numeric, "filename": filename})

    def test_unknown_position_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(GoSymbolReachabilityError, "unsupported"):
            self._parsed_position({
                "filename": "pkg/dep.go",
                "offset": 18,
                "line": 3,
                "column": 6,
                "future_field": 1,
            })

    def test_none_position_remains_absent(self) -> None:
        self.assertIsNone(self._parsed_position(None))


if __name__ == "__main__":
    unittest.main()
