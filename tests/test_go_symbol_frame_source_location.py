from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from unified_project_manager.go_symbol_frame_source_location import (
    validate_positioned_govulncheck_frame_source_location,
)
from unified_project_manager.go_symbol_reachability import GovulncheckFrame
from unified_project_manager.go_symbol_source_observation import (
    GoSymbolBuildEnvironment,
    GoSymbolModuleInput,
    GoSymbolPackageInput,
    GoSymbolSourceObservation,
)


class GoSymbolFrameSourceLocationTests(unittest.TestCase):
    def _observation(self, package_dir: Path, *, syntax_file: str = "dep.go") -> GoSymbolSourceObservation:
        package = GoSymbolPackageInput(
            import_path="example.com/dep/pkg",
            name="pkg",
            standard=False,
            dep_only=True,
            directory=str(package_dir),
            module=GoSymbolModuleInput(
                path="example.com/dep",
                version="v1.2.3",
                main=False,
                effective_path="example.com/dep",
                effective_version="v1.2.3",
            ),
            compiled_go_files=(syntax_file,),
            source_files=(("GoFiles", ("dep.go",)),),
            ignored_files=(),
            imports=(),
        )
        return GoSymbolSourceObservation(
            GoSymbolBuildEnvironment((("GOOS", "linux"), ("GOARCH", "amd64"), ("GOVERSION", "go1.25.0"))),
            (package,),
        )

    def _frame(self, data: bytes, *, offset: int | None = None, line: int | None = None, column: int | None = None):
        actual_offset = data.index(b"Danger") if offset is None else offset
        prefix = data[:actual_offset]
        actual_line = prefix.count(b"\n") + 1
        last_newline = prefix.rfind(b"\n")
        actual_column = actual_offset + 1 if last_newline < 0 else actual_offset - last_newline
        position = {
            "filename": "pkg/dep.go",
            "offset": actual_offset,
            "line": actual_line if line is None else line,
            "column": actual_column if column is None else column,
        }
        return GovulncheckFrame(
            module="example.com/dep",
            version="v1.2.3",
            package="example.com/dep/pkg",
            function="Danger",
            receiver=None,
            position=position,
        )

    def _fixture(self, data: bytes):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        package_dir = root / "module" / "pkg"
        package_dir.mkdir(parents=True)
        source = package_dir / "dep.go"
        source.write_bytes(data)
        return temporary, package_dir, source

    def test_ascii_position_matches_current_source_bytes(self) -> None:
        data = b'package pkg\n\nfunc Danger() string { return "x" }\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual(result.scanner_offset, data.index(b"Danger"))
        self.assertEqual(result.scanner_line, 3)
        self.assertEqual(result.scanner_column, 6)
        self.assertEqual(result.observed_offset_line, 3)
        self.assertEqual(result.observed_offset_column, 6)
        self.assertEqual(result.source_size_bytes, len(data))

    def test_column_uses_utf8_byte_count(self) -> None:
        data = "package pkg\n\nvar π = Danger\n".encode("utf-8")
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual(result.scanner_line, 3)
        self.assertEqual(result.scanner_column, 10)

    def test_tab_counts_as_one_byte_not_display_width(self) -> None:
        data = b'package pkg\n\n\tfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual((result.scanner_line, result.scanner_column), (3, 7))

    def test_crlf_line_tracking_uses_raw_bytes(self) -> None:
        data = b'package pkg\r\n\r\nfunc Danger() {}\r\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual((result.scanner_line, result.scanner_column), (3, 6))

    def test_eof_position_is_valid_when_coordinates_match(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        offset = len(data)
        prefix = data[:offset]
        line = prefix.count(b"\n") + 1
        last_newline = prefix.rfind(b"\n")
        column = offset + 1 if last_newline < 0 else offset - last_newline
        frame = GovulncheckFrame(
            module="example.com/dep",
            version="v1.2.3",
            package="example.com/dep/pkg",
            function="Danger",
            receiver=None,
            position={
                "filename": "pkg/dep.go",
                "offset": offset,
                "line": line,
                "column": column,
            },
        )
        result = validate_positioned_govulncheck_frame_source_location(
            frame, self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual((result.scanner_line, result.scanner_column), (4, 1))

    def test_possible_go_line_directive_fails_closed_before_raw_coordinate_claim(self) -> None:
        data = b'package pkg\n\n//line :100:1\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("line directive", result.reason)
        self.assertEqual(result.source_size_bytes, len(data))

    def test_block_line_directive_marker_also_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc x() { _ = /*line :100:1*/ Danger() }\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("line directive", result.reason)

    def test_line_directive_strictly_after_position_does_not_retroactively_block(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n//line :100:1\nfunc Later() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertTrue(result.validated, result.to_dict())

    def test_line_directive_marker_across_stream_chunk_boundary_fails_closed(self) -> None:
        chunk_size = 64 * 1024
        prefix = b"package pkg\n"
        marker_start = chunk_size - 3
        data = prefix + (b" " * (marker_start - len(prefix))) + b"/*line :100:1*/\nfunc Danger() {}\n"
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("line directive", result.reason)

    def test_witness_streams_only_prefix_through_scanner_offset(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n' + (b'x' * (2 * 1024 * 1024))
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        expected_offset = data.index(b"Danger")
        real_read = os.read
        observed_bytes = 0

        def recording_read(descriptor, count):
            nonlocal observed_bytes
            chunk = real_read(descriptor, count)
            observed_bytes += len(chunk)
            return chunk

        with patch(
            "unified_project_manager.go_symbol_frame_source_location.os.read",
            side_effect=recording_read,
        ):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual(observed_bytes, expected_offset)
        self.assertLess(observed_bytes, len(data))

    def test_line_or_column_mismatch_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        wrong_line = validate_positioned_govulncheck_frame_source_location(
            self._frame(data, line=4), self._observation(package_dir)
        )
        self.assertFalse(wrong_line.validated)
        self.assertIn("does not agree", wrong_line.reason)
        self.assertEqual((wrong_line.observed_offset_line, wrong_line.observed_offset_column), (3, 6))

        wrong_column = validate_positioned_govulncheck_frame_source_location(
            self._frame(data, column=7), self._observation(package_dir)
        )
        self.assertFalse(wrong_column.validated)
        self.assertIn("does not agree", wrong_column.reason)

    def test_offset_outside_file_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data, offset=len(data) + 1), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("outside", result.reason)
        self.assertEqual(result.source_size_bytes, len(data))

    def test_unknown_zero_column_is_insufficient_for_exact_byte_location_witness(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data, column=0), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("column", result.reason)
        self.assertIn(">= 1", result.reason)

    def test_effective_replacement_identity_remains_usable_for_location_witness(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        package = GoSymbolPackageInput(
            import_path="example.com/original/pkg",
            name="pkg",
            standard=False,
            dep_only=True,
            directory=str(package_dir),
            module=GoSymbolModuleInput(
                path="example.com/original",
                version="v1.2.3",
                main=False,
                effective_path="example.com/fork",
                effective_version="v1.2.3-fixed",
            ),
            compiled_go_files=("dep.go",),
            source_files=(("GoFiles", ("dep.go",)),),
            ignored_files=(),
            imports=(),
        )
        observation = GoSymbolSourceObservation(
            GoSymbolBuildEnvironment((("GOOS", "linux"), ("GOARCH", "amd64"), ("GOVERSION", "go1.25.0"))),
            (package,),
        )
        base = self._frame(data)
        frame = GovulncheckFrame(
            module="example.com/fork",
            version="v1.2.3-fixed",
            package="example.com/original/pkg",
            function=base.function,
            receiver=base.receiver,
            position=base.position,
        )
        result = validate_positioned_govulncheck_frame_source_location(frame, observation)
        self.assertTrue(result.validated, result.to_dict())
        self.assertEqual(result.alignment.observed_module, "example.com/fork")

    def test_missing_or_invalid_numeric_position_is_explicit(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        frame = self._frame(data)
        position = dict(frame.position)
        del position["offset"]
        missing = GovulncheckFrame(frame.module, frame.version, frame.package, frame.function, frame.receiver, position)
        result = validate_positioned_govulncheck_frame_source_location(missing, self._observation(package_dir))
        self.assertFalse(result.validated)
        self.assertIn("offset", result.reason)

        position = dict(frame.position)
        position["line"] = 0
        invalid = GovulncheckFrame(frame.module, frame.version, frame.package, frame.function, frame.receiver, position)
        result = validate_positioned_govulncheck_frame_source_location(invalid, self._observation(package_dir))
        self.assertFalse(result.validated)
        self.assertIn("line", result.reason)

        position = dict(frame.position)
        position["column"] = True
        invalid = GovulncheckFrame(frame.module, frame.version, frame.package, frame.function, frame.receiver, position)
        result = validate_positioned_govulncheck_frame_source_location(invalid, self._observation(package_dir))
        self.assertFalse(result.validated)
        self.assertIn("column", result.reason)

    def test_relative_observed_package_directory_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(Path("relative/package"))
        )
        self.assertFalse(result.validated)
        self.assertIn("package directory is not absolute", result.reason)

    def test_symlinked_package_directory_is_rejected_without_host_symlink_privilege(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_lstat = os.lstat

        def fake_lstat(path):
            observed = real_lstat(path)
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(package_dir))):
                return SimpleNamespace(
                    st_mode=stat.S_IFLNK | 0o777,
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                )
            return observed

        with patch("unified_project_manager.go_symbol_frame_source_location.os.lstat", side_effect=fake_lstat):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("package directory", result.reason)
        self.assertIn("symlink", result.reason)

    def test_missing_source_file_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        source.unlink()
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("inspect observed syntax file", result.reason)

    def test_non_regular_source_file_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        source.unlink()
        source.mkdir()
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        self.assertFalse(result.validated)
        self.assertIn("not a regular file", result.reason)

    def test_symlink_source_file_is_rejected_without_requiring_host_symlink_privilege(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_lstat = os.lstat

        def fake_lstat(path):
            observed = real_lstat(path)
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(source))):
                return SimpleNamespace(
                    st_mode=stat.S_IFLNK | 0o777,
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                )
            return observed

        with patch("unified_project_manager.go_symbol_frame_source_location.os.lstat", side_effect=fake_lstat):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("symlink", result.reason)

    def test_windows_reparse_point_source_is_rejected_when_attribute_is_available(self) -> None:
        if not hasattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT"):
            self.skipTest("Python stat module does not expose Windows reparse-point flag")
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_lstat = os.lstat

        def fake_lstat(path):
            observed = real_lstat(path)
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(source))):
                return SimpleNamespace(
                    st_mode=observed.st_mode,
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                    st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
                )
            return observed

        with patch("unified_project_manager.go_symbol_frame_source_location.os.lstat", side_effect=fake_lstat):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("reparse point", result.reason)

    def test_file_identity_change_before_read_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_fstat = os.fstat

        def changed_identity(descriptor):
            observed = real_fstat(descriptor)
            return SimpleNamespace(
                st_dev=observed.st_dev,
                st_ino=observed.st_ino + 1,
                st_size=observed.st_size,
                st_mtime_ns=getattr(observed, "st_mtime_ns", None),
                st_ctime_ns=getattr(observed, "st_ctime_ns", None),
            )

        with patch("unified_project_manager.go_symbol_frame_source_location.os.fstat", side_effect=changed_identity):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("identity changed", result.reason)

    def test_cross_view_ctime_difference_does_not_fake_source_mutation(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_fstat = os.fstat

        def different_handle_ctime(descriptor):
            observed = real_fstat(descriptor)
            return SimpleNamespace(
                st_dev=observed.st_dev,
                st_ino=observed.st_ino,
                st_size=observed.st_size,
                st_mtime_ns=getattr(observed, "st_mtime_ns", None),
                st_ctime_ns=getattr(observed, "st_ctime_ns", 0) + 1_000_000,
            )

        with patch(
            "unified_project_manager.go_symbol_frame_source_location.os.fstat",
            side_effect=different_handle_ctime,
        ):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertTrue(result.validated, result.to_dict())

    def test_package_directory_replacement_after_read_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_lstat = os.lstat
        package_calls = 0

        def replaced_parent(path):
            nonlocal package_calls
            observed = real_lstat(path)
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(package_dir))):
                package_calls += 1
                if package_calls > 1:
                    return SimpleNamespace(
                        st_mode=observed.st_mode,
                        st_dev=observed.st_dev,
                        st_ino=observed.st_ino + 1,
                        st_file_attributes=getattr(observed, "st_file_attributes", 0),
                    )
            return observed

        with patch("unified_project_manager.go_symbol_frame_source_location.os.lstat", side_effect=replaced_parent):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("parent path changed", result.reason)

    def test_source_path_replacement_after_read_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_lstat = os.lstat
        source_calls = 0

        def replaced_path(path):
            nonlocal source_calls
            observed = real_lstat(path)
            if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(source))):
                source_calls += 1
                if source_calls > 1:
                    return SimpleNamespace(
                        st_mode=observed.st_mode,
                        st_dev=observed.st_dev,
                        st_ino=observed.st_ino + 1,
                        st_size=observed.st_size,
                        st_mtime_ns=getattr(observed, "st_mtime_ns", None),
                        st_ctime_ns=getattr(observed, "st_ctime_ns", None),
                        st_file_attributes=getattr(observed, "st_file_attributes", 0),
                    )
            return observed

        with patch("unified_project_manager.go_symbol_frame_source_location.os.lstat", side_effect=replaced_path):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("path changed", result.reason)

    def test_file_mutation_during_read_fails_closed(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        real_fstat = os.fstat
        calls = 0

        def changed_mtime(descriptor):
            nonlocal calls
            calls += 1
            observed = real_fstat(descriptor)
            return SimpleNamespace(
                st_dev=observed.st_dev,
                st_ino=observed.st_ino,
                st_size=observed.st_size,
                st_mtime_ns=getattr(observed, "st_mtime_ns", 0) + (1 if calls > 1 else 0),
                st_ctime_ns=getattr(observed, "st_ctime_ns", 0) + (1 if calls > 1 else 0),
            )

        with patch("unified_project_manager.go_symbol_frame_source_location.os.fstat", side_effect=changed_mtime):
            result = validate_positioned_govulncheck_frame_source_location(
                self._frame(data), self._observation(package_dir)
            )
        self.assertFalse(result.validated)
        self.assertIn("changed while", result.reason)

    def test_absolute_syntax_file_inside_package_is_supported(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir, syntax_file=str(source))
        )
        self.assertTrue(result.validated, result.to_dict())

    def test_result_never_upgrades_freshness_or_public_semantics(self) -> None:
        data = b'package pkg\n\nfunc Danger() {}\n'
        temporary, package_dir, _source = self._fixture(data)
        self.addCleanup(temporary.cleanup)
        result = validate_positioned_govulncheck_frame_source_location(
            self._frame(data), self._observation(package_dir)
        )
        payload = result.to_dict()
        self.assertTrue(result.validated)
        self.assertEqual(payload["freshness"], "not-established")
        self.assertEqual(payload["call_graph_freshness"], "not-established")
        self.assertEqual(payload["source_selection_equivalence"], "not-established")
        self.assertEqual(payload["build_configuration_equivalence"], "not-established")
        self.assertFalse(payload["source_state_fingerprint"])
        self.assertEqual(payload["symbol_text_correspondence"], "not-established")
        self.assertEqual(payload["project_content_mutation"], "none-planned")
        self.assertEqual(
            payload["filesystem_metadata_side_effects"],
            "possible-access-time-not-characterized",
        )
        self.assertFalse(payload["public"])
        self.assertFalse(payload["persisted"])
        self.assertEqual(payload["runtime_reachability"], "not-evaluated")
        self.assertEqual(payload["exploitability"], "not-established")


if __name__ == "__main__":
    unittest.main()
