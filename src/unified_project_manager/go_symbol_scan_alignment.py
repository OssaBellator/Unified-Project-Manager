from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .go_symbol_reachability import GoSymbolReachabilityError, GovulncheckReport
from .go_symbol_source_observation import GoSymbolSourceObservation


@dataclass(frozen=True)
class GoSymbolScanAlignment:
    observation_roots: tuple[str, ...]
    scanner_roots: tuple[str, ...]
    observation_modules: tuple[tuple[str, str | None], ...]
    scanner_modules: tuple[tuple[str, str | None], ...]
    observation_go_version: str | None
    scanner_config_go_version: str | None
    scanner_sbom_go_version: str | None

    @property
    def roots_match(self) -> bool:
        return self.observation_roots == self.scanner_roots

    @property
    def modules_match(self) -> bool:
        return self.observation_modules == self.scanner_modules

    @property
    def declared_inventory_match(self) -> bool:
        return self.roots_match and self.modules_match

    @property
    def go_version_match(self) -> bool:
        return (
            self.observation_go_version is not None
            and self.observation_go_version == self.scanner_config_go_version
            and self.observation_go_version == self.scanner_sbom_go_version
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_roots": list(self.observation_roots),
            "scanner_roots": list(self.scanner_roots),
            "observation_modules": [
                {"path": path, "version": version}
                for path, version in self.observation_modules
            ],
            "scanner_modules": [
                {"path": path, "version": version}
                for path, version in self.scanner_modules
            ],
            "observation_go_version": self.observation_go_version,
            "scanner_config_go_version": self.scanner_config_go_version,
            "scanner_sbom_go_version": self.scanner_sbom_go_version,
            "roots_match": self.roots_match,
            "modules_match": self.modules_match,
            "declared_inventory_match": self.declared_inventory_match,
            "go_version_match": self.go_version_match,
            "scope": "go-observation-vs-govulncheck-scan-declaration",
            "freshness": "not-established",
            "source_selection_equivalence": "not-established",
            "build_configuration_equivalence": "not-established",
            "interpretation": (
                "agreement separately compares Go-native root/module inventory and exact Go toolchain version "
                "with govulncheck's declared scan evidence; it does not establish identical source-file selection, "
                "build configuration, call graph, or freshness"
            ),
        }


def _observation_modules(
    observation: GoSymbolSourceObservation,
) -> tuple[tuple[str, str | None], ...]:
    values = {
        (package.module.effective_path, package.module.effective_version)
        for package in observation.packages
        if package.module is not None and not package.standard
    }
    return tuple(sorted(values, key=lambda item: (item[0], item[1] or "")))


def compare_go_symbol_observation_to_scan_sbom(
    observation: GoSymbolSourceObservation,
    report: GovulncheckReport,
) -> GoSymbolScanAlignment:
    """Compare two declared inventories without upgrading the result to freshness.

    The Go-native observation and govulncheck scan evidence come from different
    package-loading paths. This function separately compares normalized root
    package/effective module-version sets and exact Go toolchain versions. Those
    matches are useful consistency evidence; they are not proof of identical
    compiled files, build flags, source selection, or call-graph inputs.
    """

    if report.sbom is None:
        raise GoSymbolReachabilityError(
            "Cannot compare Go source observation without govulncheck scan SBOM evidence"
        )
    scanner_modules = tuple(sorted(
        {(module.path, module.version) for module in report.sbom.modules},
        key=lambda item: (item[0], item[1] or ""),
    ))
    return GoSymbolScanAlignment(
        observation_roots=tuple(sorted(set(observation.root_packages))),
        scanner_roots=tuple(sorted(set(report.sbom.roots))),
        observation_modules=_observation_modules(observation),
        scanner_modules=scanner_modules,
        observation_go_version=observation.build_environment.get("GOVERSION"),
        scanner_config_go_version=report.config.go_version,
        scanner_sbom_go_version=report.sbom.go_version,
    )
