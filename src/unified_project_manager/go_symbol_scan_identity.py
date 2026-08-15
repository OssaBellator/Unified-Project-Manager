from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .go_symbol_reachability import GoSymbolReachabilityError, GovulncheckReport


@dataclass(frozen=True)
class GovulncheckScanDeclarationIdentity:
    protocol_version: str
    scanner_name: str | None
    scanner_version: str | None
    database: str
    database_last_modified: str | None
    config_go_version: str | None
    sbom_go_version: str | None
    modules: tuple[tuple[str, str | None], ...]
    roots: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "scanner_name": self.scanner_name,
            "scanner_version": self.scanner_version,
            "database": self.database,
            "database_last_modified": self.database_last_modified,
            "config_go_version": self.config_go_version,
            "sbom_go_version": self.sbom_go_version,
            "modules": [
                {"path": path, "version": version}
                for path, version in self.modules
            ],
            "roots": list(self.roots),
            "scope": "govulncheck-scan-declaration",
            "freshness": "not-established",
            "source_state_fingerprint": False,
            "build_configuration_fingerprint": False,
            "interpretation": (
                "identity of the scanner-declared govulncheck config/SBOM only; "
                "matching identity does not establish unchanged source, build configuration, "
                "call graph, runtime behavior, or exploitability"
            ),
        }

    def canonical_bytes(self) -> bytes:
        payload = {
            "protocol_version": self.protocol_version,
            "scanner_name": self.scanner_name,
            "scanner_version": self.scanner_version,
            "database": self.database,
            "database_last_modified": self.database_last_modified,
            "config_go_version": self.config_go_version,
            "sbom_go_version": self.sbom_go_version,
            "modules": [list(item) for item in self.modules],
            "roots": list(self.roots),
        }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def govulncheck_scan_declaration_identity(
    report: GovulncheckReport,
) -> GovulncheckScanDeclarationIdentity:
    """Return deterministic identity for govulncheck's own scan declaration.

    This deliberately fingerprints only evidence carried by the validated
    govulncheck config/SBOM. It is useful for provenance and exact-report
    association, but it is not a source/build freshness fingerprint.
    """

    if report.sbom is None:
        raise GoSymbolReachabilityError(
            "Cannot identify govulncheck scan declaration without retained SBOM evidence"
        )
    return GovulncheckScanDeclarationIdentity(
        protocol_version=report.config.protocol_version,
        scanner_name=report.config.scanner_name,
        scanner_version=report.config.scanner_version,
        database=report.config.database,
        database_last_modified=report.config.database_last_modified,
        config_go_version=report.config.go_version,
        sbom_go_version=report.sbom.go_version,
        modules=tuple((module.path, module.version) for module in report.sbom.modules),
        roots=report.sbom.roots,
    )
