from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .go_symbol_frame_source_alignment import (
    GoSymbolFrameSourceAlignment,
    compare_positioned_govulncheck_frame_to_source_observation,
)
from .go_symbol_reachability import GovulncheckFrame
from .go_symbol_source_observation import GoSymbolPackageInput, GoSymbolSourceObservation


@dataclass(frozen=True)
class GoSymbolFrameSourceLocation:
    validated: bool
    reason: str
    alignment: GoSymbolFrameSourceAlignment
    scanner_offset: int | None
    scanner_line: int | None
    scanner_column: int | None
    observed_offset_line: int | None
    observed_offset_column: int | None
    source_size_bytes: int | None
    observed_source_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "alignment": self.alignment.to_dict(),
            "scope": "govulncheck-position-vs-current-observed-source-bytes",
            "source_selection_equivalence": "not-established",
            "build_configuration_equivalence": "not-established",
            "freshness": "not-established",
            "call_graph_freshness": "not-established",
            "source_state_fingerprint": False,
            "symbol_text_correspondence": "not-established",
            "project_content_mutation": "none-planned",
            "filesystem_metadata_side_effects": "possible-access-time-not-characterized",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "public": False,
            "persisted": False,
            "interpretation": (
                "validation establishes only that this scanner position's byte offset, line, and column agree "
                "with the current bytes of the already-correlated observed syntax file; it is not a persisted "
                "source fingerprint and does not establish symbol-text correspondence, complete source selection, "
                "build equivalence, call-graph freshness, runtime reachability, or exploitability; possible Go line directives "
                "are refused because they can adjust token line/column positions; reading the source may affect "
                "filesystem access-time metadata depending on platform policy, which is not characterized here"
            ),
        }


def _position_number(position: dict[str, Any], name: str, *, minimum: int) -> tuple[int | None, str | None]:
    value = position.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        return None, f"govulncheck position {name} is missing or not an integer"
    if value < minimum:
        return None, f"govulncheck position {name} must be >= {minimum}"
    return value, None


def _result(
    alignment: GoSymbolFrameSourceAlignment,
    *,
    validated: bool,
    reason: str,
    offset: int | None = None,
    line: int | None = None,
    column: int | None = None,
    observed_line: int | None = None,
    observed_column: int | None = None,
    source_size: int | None = None,
    source_path: str | None = None,
) -> GoSymbolFrameSourceLocation:
    return GoSymbolFrameSourceLocation(
        validated=validated,
        reason=reason,
        alignment=alignment,
        scanner_offset=offset,
        scanner_line=line,
        scanner_column=column,
        observed_offset_line=observed_line,
        observed_offset_column=observed_column,
        source_size_bytes=source_size,
        observed_source_path=source_path,
    )


def _matching_package(
    alignment: GoSymbolFrameSourceAlignment,
    observation: GoSymbolSourceObservation,
) -> GoSymbolPackageInput | None:
    candidates = [
        package
        for package in observation.packages
        if package.import_path == alignment.observed_package
        and package.module is not None
        and package.module.effective_path == alignment.observed_module
        and package.module.effective_version == alignment.observed_version
    ]
    return candidates[0] if len(candidates) == 1 else None


def _lexical_source_path(
    package: GoSymbolPackageInput,
    syntax_file: str,
) -> tuple[str | None, str | None]:
    package_directory = os.path.normpath(package.directory)
    if not os.path.isabs(package_directory):
        return None, "observed package directory is not absolute"
    package_directory = os.path.abspath(package_directory)

    source = syntax_file if os.path.isabs(syntax_file) else os.path.join(package_directory, syntax_file)
    source_path = os.path.abspath(os.path.normpath(source))
    try:
        package_key = os.path.normcase(package_directory)
        source_key = os.path.normcase(source_path)
        if os.path.commonpath((package_key, source_key)) != package_key:
            return None, "observed syntax file escapes the observed package directory"
    except ValueError:
        return None, "observed syntax file is on a different filesystem root than the package directory"
    return source_path, None


def _is_reparse_or_symlink(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _content_metadata_stamp(metadata: os.stat_result) -> tuple[int, int | None]:
    """Metadata that is comparable between path and open-handle stat views."""

    return (
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", None),
    )


def _same_view_metadata_stamp(metadata: os.stat_result) -> tuple[int, int | None, int | None]:
    """Metadata used for repeated observations through the same stat interface."""

    return (
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", None),
        getattr(metadata, "st_ctime_ns", None),
    )


@dataclass(frozen=True)
class _SourcePositionObservation:
    source_path: str | None
    source_size: int | None
    line: int | None
    column: int | None
    possible_line_directive: bool
    error: str | None


_READ_CHUNK_SIZE = 64 * 1024
_LINE_DIRECTIVE_MARKERS = (b"//line ", b"/*line ")
_LINE_DIRECTIVE_TAIL = max(len(marker) for marker in _LINE_DIRECTIVE_MARKERS) - 1


def _source_observation_error(
    error: str,
    *,
    source_path: str | None = None,
    source_size: int | None = None,
) -> _SourcePositionObservation:
    return _SourcePositionObservation(
        source_path=source_path,
        source_size=source_size,
        line=None,
        column=None,
        possible_line_directive=False,
        error=error,
    )


def _observe_stable_regular_source_position(
    package: GoSymbolPackageInput,
    syntax_file: str,
    offset: int,
) -> _SourcePositionObservation:
    source_path, path_error = _lexical_source_path(package, syntax_file)
    if path_error is not None or source_path is None:
        return _source_observation_error(path_error or "could not resolve observed syntax file")

    package_directory = os.path.abspath(os.path.normpath(package.directory))
    try:
        relative = os.path.relpath(source_path, package_directory)
    except ValueError:
        return _source_observation_error(
            "could not relate observed syntax file to package directory",
            source_path=source_path,
        )

    current = Path(package_directory)
    parent_identities: list[tuple[Path, tuple[int, int]]] = []
    try:
        root_stat = os.lstat(current)
    except OSError as exc:
        return _source_observation_error(
            f"could not inspect observed package directory: {exc}",
            source_path=source_path,
        )
    if _is_reparse_or_symlink(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        return _source_observation_error(
            "observed package directory is a symlink/reparse point or not a directory",
            source_path=source_path,
        )
    parent_identities.append((current, (root_stat.st_dev, root_stat.st_ino)))

    parts = Path(relative).parts
    for part in parts[:-1]:
        current = current / part
        try:
            item_stat = os.lstat(current)
        except OSError as exc:
            return _source_observation_error(
                f"could not inspect observed syntax-file parent: {exc}",
                source_path=source_path,
            )
        if _is_reparse_or_symlink(item_stat) or not stat.S_ISDIR(item_stat.st_mode):
            return _source_observation_error(
                "observed syntax-file parent is a symlink/reparse point or not a directory",
                source_path=source_path,
            )
        parent_identities.append((current, (item_stat.st_dev, item_stat.st_ino)))

    try:
        before = os.lstat(source_path)
    except OSError as exc:
        return _source_observation_error(
            f"could not inspect observed syntax file: {exc}",
            source_path=source_path,
        )
    if _is_reparse_or_symlink(before) or not stat.S_ISREG(before.st_mode):
        return _source_observation_error(
            "observed syntax file is a symlink/reparse point or not a regular file",
            source_path=source_path,
            source_size=getattr(before, "st_size", None),
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        return _source_observation_error(
            f"could not open observed syntax file without following the final symlink: {exc}",
            source_path=source_path,
            source_size=before.st_size,
        )

    try:
        opened = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino)
        opened_identity = (opened.st_dev, opened.st_ino)
        if before_identity != opened_identity:
            return _source_observation_error(
                "observed syntax file identity changed before it could be read",
                source_path=source_path,
                source_size=opened.st_size,
            )
        if _content_metadata_stamp(before) != _content_metadata_stamp(opened):
            return _source_observation_error(
                "observed syntax file content metadata changed before it could be read",
                source_path=source_path,
                source_size=opened.st_size,
            )

        read_error: str | None = None
        possible_line_directive = False
        line = 1
        last_newline = -1
        processed = 0
        tail = b""

        if offset > opened.st_size:
            read_error = "govulncheck position offset is outside the current observed syntax file"
        else:
            remaining = offset
            while remaining:
                chunk = os.read(descriptor, min(_READ_CHUNK_SIZE, remaining))
                if not chunk:
                    read_error = (
                        "observed syntax file ended before the scanner position while it was being read"
                    )
                    break
                scan_window = tail + chunk
                if any(marker in scan_window for marker in _LINE_DIRECTIVE_MARKERS):
                    possible_line_directive = True
                newline_count = chunk.count(b"\n")
                line += newline_count
                last = chunk.rfind(b"\n")
                if last >= 0:
                    last_newline = processed + last
                processed += len(chunk)
                remaining -= len(chunk)
                tail = scan_window[-_LINE_DIRECTIVE_TAIL:]

        after = os.fstat(descriptor)
        if _same_view_metadata_stamp(opened) != _same_view_metadata_stamp(after):
            return _source_observation_error(
                "observed syntax file changed while its position was being validated",
                source_path=source_path,
                source_size=after.st_size,
            )

        for parent_path, expected_identity in parent_identities:
            try:
                final_parent = os.lstat(parent_path)
            except OSError as exc:
                return _source_observation_error(
                    f"could not re-inspect observed syntax-file parent after reading: {exc}",
                    source_path=source_path,
                    source_size=after.st_size,
                )
            if _is_reparse_or_symlink(final_parent) or not stat.S_ISDIR(final_parent.st_mode):
                return _source_observation_error(
                    "observed syntax-file parent became a symlink/reparse point or non-directory while reading",
                    source_path=source_path,
                    source_size=after.st_size,
                )
            if (final_parent.st_dev, final_parent.st_ino) != expected_identity:
                return _source_observation_error(
                    "observed syntax-file parent path changed while its position was being validated",
                    source_path=source_path,
                    source_size=after.st_size,
                )

        try:
            final_path = os.lstat(source_path)
        except OSError as exc:
            return _source_observation_error(
                f"could not re-inspect observed syntax file after reading: {exc}",
                source_path=source_path,
                source_size=after.st_size,
            )
        if _is_reparse_or_symlink(final_path) or not stat.S_ISREG(final_path.st_mode):
            return _source_observation_error(
                "observed syntax file became a symlink/reparse point or non-regular file while being read",
                source_path=source_path,
                source_size=after.st_size,
            )
        final_identity = (final_path.st_dev, final_path.st_ino)
        if final_identity != opened_identity:
            return _source_observation_error(
                "observed syntax file path changed while its position was being validated",
                source_path=source_path,
                source_size=after.st_size,
            )
        if _same_view_metadata_stamp(before) != _same_view_metadata_stamp(final_path):
            return _source_observation_error(
                "observed syntax file path metadata changed while its position was being validated",
                source_path=source_path,
                source_size=after.st_size,
            )
        if _content_metadata_stamp(final_path) != _content_metadata_stamp(after):
            return _source_observation_error(
                "observed syntax file path and open handle disagree after position validation",
                source_path=source_path,
                source_size=after.st_size,
            )

        if read_error is not None:
            return _source_observation_error(
                read_error,
                source_path=source_path,
                source_size=after.st_size,
            )

        column = offset + 1 if last_newline < 0 else offset - last_newline
        return _SourcePositionObservation(
            source_path=source_path,
            source_size=after.st_size,
            line=line,
            column=column,
            possible_line_directive=possible_line_directive,
            error=None,
        )
    finally:
        os.close(descriptor)


def validate_positioned_govulncheck_frame_source_location(
    frame: GovulncheckFrame,
    observation: GoSymbolSourceObservation,
) -> GoSymbolFrameSourceLocation:
    """Validate one scanner byte position against current observed source bytes.

    This function is deliberately narrower than a source-state fingerprint. It
    first requires the existing module/package/syntax-file correspondence, then
    streams only the observed syntax-file prefix up to govulncheck's byte offset
    and checks the reported 1-based line and byte column against those bytes at
    validation time. Symlinks/reparse points, non-regular files, path escapes, missing numeric
    coordinates, file replacement, concurrent mutation, and possible Go line
    directives fail closed. Line directives are refused because Go token positions
    may be adjusted away from raw source line/column coordinates.
    """

    alignment = compare_positioned_govulncheck_frame_to_source_observation(frame, observation)
    if not alignment.matched:
        return _result(
            alignment,
            validated=False,
            reason="frame/source correspondence is required before source-byte position validation",
        )

    if not isinstance(frame.position, dict):
        return _result(alignment, validated=False, reason="govulncheck position is absent")
    offset, error = _position_number(frame.position, "offset", minimum=0)
    if error is not None:
        return _result(alignment, validated=False, reason=error)
    line, error = _position_number(frame.position, "line", minimum=1)
    if error is not None:
        return _result(alignment, validated=False, reason=error, offset=offset)
    column, error = _position_number(frame.position, "column", minimum=1)
    if error is not None:
        return _result(alignment, validated=False, reason=error, offset=offset, line=line)

    package = _matching_package(alignment, observation)
    if package is None or alignment.observed_syntax_file is None:
        return _result(
            alignment,
            validated=False,
            reason="matched frame/source evidence could not be re-associated with exactly one observed package/file",
            offset=offset,
            line=line,
            column=column,
        )

    observed = _observe_stable_regular_source_position(
        package,
        alignment.observed_syntax_file,
        offset,
    )
    if observed.error is not None:
        return _result(
            alignment,
            validated=False,
            reason=observed.error,
            offset=offset,
            line=line,
            column=column,
            source_size=observed.source_size,
            source_path=observed.source_path,
        )

    if observed.possible_line_directive:
        return _result(
            alignment,
            validated=False,
            reason=(
                "current observed syntax-file prefix contains a possible Go line directive; "
                "raw source bytes cannot establish scanner line/column coordinates that may be adjusted"
            ),
            offset=offset,
            line=line,
            column=column,
            source_size=observed.source_size,
            source_path=observed.source_path,
        )

    observed_line = observed.line
    observed_column = observed.column
    if observed_line is None or observed_column is None:
        return _result(
            alignment,
            validated=False,
            reason="current observed syntax-file prefix did not yield usable raw coordinates",
            offset=offset,
            line=line,
            column=column,
            source_size=observed.source_size,
            source_path=observed.source_path,
        )
    if (observed_line, observed_column) != (line, column):
        return _result(
            alignment,
            validated=False,
            reason="govulncheck offset does not agree with its reported line/byte-column in current source bytes",
            offset=offset,
            line=line,
            column=column,
            observed_line=observed_line,
            observed_column=observed_column,
            source_size=observed.source_size,
            source_path=observed.source_path,
        )

    return _result(
        alignment,
        validated=True,
        reason="govulncheck byte offset, line, and byte-column agree with the current observed syntax file",
        offset=offset,
        line=line,
        column=column,
        observed_line=observed_line,
        observed_column=observed_column,
        source_size=observed.source_size,
        source_path=observed.source_path,
    )
