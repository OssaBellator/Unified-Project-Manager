from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .go_symbol_reachability import GovulncheckFinding, GovulncheckReport


@dataclass(frozen=True)
class GovulncheckSymbolMatch:
    advisory_id: str
    govulncheck_osv: str
    component: str
    module: str
    version: str
    package: str | None
    symbol: str
    fixed_version: str | None
    advisory_identity: str
    dependency_paths: tuple[tuple[str, ...], ...]
    trace: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "dependency_paths": [list(path) for path in self.dependency_paths],
            "trace": list(self.trace),
            "provider": "govulncheck",
            "scope": "vulnerable-symbol-call-graph",
            "correlation": "advisory+effective-module+exact-version",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "persisted": False,
        }


@dataclass(frozen=True)
class GovulncheckUnmatchedSymbol:
    govulncheck_osv: str
    module: str
    version: str | None
    package: str | None
    symbol: str
    reason: str
    known_advisory_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovulncheckSymbolCorrelation:
    component: str
    matches: tuple[GovulncheckSymbolMatch, ...]
    unmatched: tuple[GovulncheckUnmatchedSymbol, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "matches": [item.to_dict() for item in self.matches],
            "unmatched": [item.to_dict() for item in self.unmatched],
            "provider": "govulncheck",
            "scope": "vulnerable-symbol-call-graph",
            "public": False,
            "interpretation": (
                "pre-public static vulnerable-symbol call-graph correlation only; "
                "runtime/data-flow reachability and exploitability are not established"
            ),
        }


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dependency_paths(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    paths: set[tuple[str, ...]] = set()
    for path in value:
        if not isinstance(path, (list, tuple)):
            continue
        nodes = tuple(node for node in path if isinstance(node, str) and node)
        if nodes:
            paths.add(nodes)
    return tuple(sorted(paths))


def _go_impact_identity(impact: object, component: str) -> dict[str, Any] | None:
    if not isinstance(impact, dict):
        return None
    if impact.get("provider") != "go-modules" or impact.get("component") != component:
        return None
    advisory_id = _string(impact.get("advisory_id"))
    version = _string(impact.get("version"))
    evidence = impact.get("evidence")
    if advisory_id is None or version is None or not isinstance(evidence, dict):
        return None
    logical_module = _string(evidence.get("module"))
    effective_module = _string(evidence.get("effective_name"))
    if logical_module is None or effective_module is None:
        return None
    return {
        "advisory_id": advisory_id,
        "version": version,
        "logical_module": logical_module,
        "effective_module": effective_module,
        "dependency_paths": _dependency_paths(impact.get("paths")),
    }


def _finding_identity(finding: GovulncheckFinding) -> tuple[str, str | None, str | None, str] | None:
    if finding.level != "symbol":
        return None
    frame = finding.vulnerable_frame
    if frame is None or frame.symbol is None:
        return None
    return frame.module, frame.version, frame.package, frame.symbol


def correlate_govulncheck_symbols(
    report: GovulncheckReport,
    dependency_impacts: list[dict[str, Any]],
    *,
    component: str,
) -> GovulncheckSymbolCorrelation:
    """Correlate pre-public govulncheck symbol findings to exact Go advisory impacts.

    Correlation is deliberately strict. A symbol finding must match an existing
    Go dependency impact for the same component by govulncheck OSV id (or an
    alias carried by that exact OSV record), effective module path, and exact
    module version. Alias overlap never bypasses module/version identity.

    Go's vulnerability machinery uses replacement module path/version for
    vulnerability lookup/reporting, so replacement-aware UPM impacts correlate
    against ``effective_name`` rather than the logical required module path.
    """

    impacts = [
        identity
        for impact in dependency_impacts
        if (identity := _go_impact_identity(impact, component)) is not None
    ]

    matches: list[GovulncheckSymbolMatch] = []
    unmatched: list[GovulncheckUnmatchedSymbol] = []

    for finding in report.symbol_findings:
        identity = _finding_identity(finding)
        if identity is None:
            continue
        module, version, package, symbol = identity
        known_ids = report.advisory_ids(finding.osv)

        advisory_candidates = [
            impact
            for impact in impacts
            if report.matches_advisory(finding.osv, impact["advisory_id"])
        ]
        if not advisory_candidates:
            unmatched.append(GovulncheckUnmatchedSymbol(
                finding.osv, module, version, package, symbol,
                "no matching UPM advisory id/alias for this component",
                known_ids,
            ))
            continue

        module_candidates = [
            impact for impact in advisory_candidates
            if impact["effective_module"] == module
        ]
        if not module_candidates:
            unmatched.append(GovulncheckUnmatchedSymbol(
                finding.osv, module, version, package, symbol,
                "advisory identity matched but effective module did not",
                known_ids,
            ))
            continue

        if version is None:
            unmatched.append(GovulncheckUnmatchedSymbol(
                finding.osv, module, version, package, symbol,
                "govulncheck symbol finding is missing module version",
                known_ids,
            ))
            continue

        version_candidates = [
            impact for impact in module_candidates
            if impact["version"] == version
        ]
        if not version_candidates:
            unmatched.append(GovulncheckUnmatchedSymbol(
                finding.osv, module, version, package, symbol,
                "advisory and effective module matched but exact version did not",
                known_ids,
            ))
            continue

        advisory_ids = {impact["advisory_id"] for impact in version_candidates}
        if len(advisory_ids) != 1:
            unmatched.append(GovulncheckUnmatchedSymbol(
                finding.osv, module, version, package, symbol,
                "multiple UPM advisory identities matched one govulncheck symbol finding",
                known_ids,
            ))
            continue

        advisory_id = next(iter(advisory_ids))
        paths = tuple(sorted({
            path
            for impact in version_candidates
            for path in impact["dependency_paths"]
        }))
        matches.append(GovulncheckSymbolMatch(
            advisory_id=advisory_id,
            govulncheck_osv=finding.osv,
            component=component,
            module=module,
            version=version,
            package=package,
            symbol=symbol,
            fixed_version=finding.fixed_version,
            advisory_identity="direct" if advisory_id == finding.osv else "alias",
            dependency_paths=paths,
            trace=tuple(frame.to_dict() for frame in finding.trace),
        ))

    matches.sort(key=lambda item: (
        item.advisory_id,
        item.module,
        item.version,
        item.package or "",
        item.symbol,
        repr(item.trace),
    ))
    unmatched.sort(key=lambda item: (
        item.govulncheck_osv,
        item.module,
        item.version or "",
        item.package or "",
        item.symbol,
        item.reason,
    ))
    return GovulncheckSymbolCorrelation(component, tuple(matches), tuple(unmatched))
