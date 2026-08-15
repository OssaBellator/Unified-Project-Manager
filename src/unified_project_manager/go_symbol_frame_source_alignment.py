from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .go_symbol_reachability import GovulncheckFrame
from .go_symbol_source_observation import GoSymbolPackageInput, GoSymbolSourceObservation


_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class GoSymbolFrameSourceAlignment:
    matched: bool
    reason: str
    scanner_module: str
    scanner_version: str | None
    scanner_package: str | None
    scanner_filename: str | None
    normalized_scanner_filename: str | None
    observed_package: str | None
    observed_module: str | None
    observed_version: str | None
    observed_syntax_file: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "scope": "govulncheck-positioned-frame-vs-go-observed-syntax-file",
            "source_selection_equivalence": "not-established",
            "build_configuration_equivalence": "not-established",
            "freshness": "not-established",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "public": False,
            "persisted": False,
            "interpretation": (
                "a match establishes only that this positioned govulncheck frame names the same effective "
                "module/version, package, and observed compiled Go syntax file; it does not establish complete "
                "go/packages versus go-list source selection, build equivalence, call-graph freshness, runtime "
                "reachability, or exploitability"
            ),
        }


def _normalized_relative_path(value: str | None) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "filename is absent"
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//") or _WINDOWS_ABSOLUTE.match(normalized):
        return None, "filename is absolute rather than module-relative"
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None, "filename escapes its module/package with '..'"
        parts.append(part)
    if not parts:
        return None, "filename has no usable path components"
    return "/".join(parts), None


def _package_relative_import_path(package: GoSymbolPackageInput) -> tuple[str | None, str | None]:
    module = package.module
    if module is None:
        return None, "observed package has no module identity"

    relatives: set[str] = set()
    for module_path in (module.path, module.effective_path):
        if package.import_path == module_path:
            relatives.add("")
        elif package.import_path.startswith(module_path + "/"):
            relatives.add(package.import_path[len(module_path) + 1 :])

    if not relatives:
        return None, "observed package import path is inconsistent with its logical/effective module identity"
    if len(relatives) != 1:
        return None, "observed package import path is ambiguous across logical/effective module identity"
    relative = next(iter(relatives))
    normalized, error = _normalized_relative_path(relative) if relative else ("", None)
    if error is not None:
        return None, error
    return normalized, None


def _normalize_absolute(value: str) -> tuple[str | None, bool]:
    normalized = value.replace("\\", "/")
    if _WINDOWS_ABSOLUTE.match(normalized):
        drive = normalized[:2].lower()
        rest = normalized[2:]
        parts: list[str] = []
        for part in rest.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return None, True
                parts.pop()
            else:
                parts.append(part)
        return drive + "/" + "/".join(parts), True
    if normalized.startswith("/"):
        parts = []
        for part in normalized.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return None, False
                parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts), False
    return None, False


def _compiled_file_relative_to_package(
    package: GoSymbolPackageInput,
    compiled_file: str,
) -> tuple[str | None, str | None]:
    absolute_file, file_is_windows = _normalize_absolute(compiled_file)
    if absolute_file is None:
        return _normalized_relative_path(compiled_file)

    package_directory, directory_is_windows = _normalize_absolute(package.directory)
    if package_directory is None or file_is_windows != directory_is_windows:
        return None, "absolute CompiledGoFiles entry cannot be related to the observed package directory"

    file_key = absolute_file.lower() if file_is_windows else absolute_file
    directory_key = package_directory.lower() if directory_is_windows else package_directory
    prefix = directory_key.rstrip("/") + "/"
    if not file_key.startswith(prefix):
        return None, "absolute CompiledGoFiles entry is outside the observed package directory"

    relative = absolute_file[len(package_directory.rstrip("/")) + 1 :]
    return _normalized_relative_path(relative)


def _result(
    frame: GovulncheckFrame,
    *,
    matched: bool,
    reason: str,
    normalized_scanner_filename: str | None = None,
    package: GoSymbolPackageInput | None = None,
    syntax_file: str | None = None,
) -> GoSymbolFrameSourceAlignment:
    filename = None
    if isinstance(frame.position, dict):
        value = frame.position.get("filename")
        filename = value if isinstance(value, str) and value else None
    module = package.module if package is not None else None
    return GoSymbolFrameSourceAlignment(
        matched=matched,
        reason=reason,
        scanner_module=frame.module,
        scanner_version=frame.version,
        scanner_package=frame.package,
        scanner_filename=filename,
        normalized_scanner_filename=normalized_scanner_filename,
        observed_package=package.import_path if package is not None else None,
        observed_module=module.effective_path if module is not None else None,
        observed_version=module.effective_version if module is not None else None,
        observed_syntax_file=syntax_file,
    )


def compare_positioned_govulncheck_frame_to_source_observation(
    frame: GovulncheckFrame,
    observation: GoSymbolSourceObservation,
) -> GoSymbolFrameSourceAlignment:
    """Fail-closed correspondence check for one positioned scanner frame.

    Govulncheck protocol filenames are module-relative. The comparison therefore
    requires exact package and effective module/version identity, reconstructs the
    module-relative package path from the observed package/module identities, and
    accepts a CompiledGoFiles entry only when it is itself relative or an absolute
    path contained by the observed package directory. Generated/cache absolute
    syntax paths outside that directory are deliberately unusable evidence.
    """

    filename = None
    if isinstance(frame.position, dict):
        value = frame.position.get("filename")
        if isinstance(value, str) and value:
            filename = value
    normalized_filename, filename_error = _normalized_relative_path(filename)
    if filename_error is not None:
        return _result(frame, matched=False, reason=f"unusable govulncheck position: {filename_error}")

    if frame.package is None:
        return _result(
            frame,
            matched=False,
            reason="govulncheck positioned frame is missing package identity",
            normalized_scanner_filename=normalized_filename,
        )

    package_candidates = [
        package for package in observation.packages if package.import_path == frame.package
    ]
    if not package_candidates:
        return _result(
            frame,
            matched=False,
            reason="govulncheck package is absent from the Go-native source observation",
            normalized_scanner_filename=normalized_filename,
        )
    if len(package_candidates) != 1:
        return _result(
            frame,
            matched=False,
            reason="multiple observed packages match the govulncheck package; correspondence is ambiguous",
            normalized_scanner_filename=normalized_filename,
        )

    package = package_candidates[0]
    if package.standard:
        return _result(
            frame,
            matched=False,
            reason="standard-library positioned-frame source correspondence is intentionally not established",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )
    if package.module is None:
        return _result(
            frame,
            matched=False,
            reason="observed non-standard package is missing module identity",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )
    if package.module.effective_path != frame.module:
        return _result(
            frame,
            matched=False,
            reason="govulncheck module does not match the observed effective module identity",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )
    if package.module.effective_version != frame.version:
        return _result(
            frame,
            matched=False,
            reason="govulncheck module version does not match the observed effective module version",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )

    package_relative, package_error = _package_relative_import_path(package)
    if package_error is not None or package_relative is None:
        return _result(
            frame,
            matched=False,
            reason=package_error or "could not derive module-relative package path",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )

    candidates: dict[str, list[str]] = {}
    rejected: list[str] = []
    for syntax_file in package.syntax_go_files:
        file_relative, file_error = _compiled_file_relative_to_package(package, syntax_file)
        if file_error is not None or file_relative is None:
            rejected.append(f"{syntax_file}: {file_error or 'unusable syntax path'}")
            continue
        module_relative = "/".join(
            part for part in (package_relative, file_relative) if part
        )
        candidates.setdefault(module_relative, []).append(syntax_file)

    if not candidates:
        detail = "; ".join(sorted(rejected)) if rejected else "no CompiledGoFiles were observed"
        return _result(
            frame,
            matched=False,
            reason="no usable observed compiled Go syntax file can support the positioned frame: " + detail,
            normalized_scanner_filename=normalized_filename,
            package=package,
        )

    matching = candidates.get(normalized_filename, [])
    if not matching:
        return _result(
            frame,
            matched=False,
            reason="govulncheck module-relative filename is absent from the observed compiled Go syntax files",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )

    distinct = tuple(sorted(set(matching)))
    if len(distinct) != 1:
        return _result(
            frame,
            matched=False,
            reason="multiple observed syntax-file records match the positioned frame; correspondence is ambiguous",
            normalized_scanner_filename=normalized_filename,
            package=package,
        )

    return _result(
        frame,
        matched=True,
        reason="positioned frame matches the observed effective module/version, package, and compiled Go syntax file",
        normalized_scanner_filename=normalized_filename,
        package=package,
        syntax_file=distinct[0],
    )
