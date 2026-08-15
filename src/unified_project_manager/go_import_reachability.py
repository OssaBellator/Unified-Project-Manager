from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from .go_offline_provider import query_native_why_offline
from .models import ProjectGraph
from .native_graph import NativeGraphSkip, NativeWhyResult


@dataclass(frozen=True)
class GoImportReachabilityEvidence:
    advisory_id: str
    package: str
    version: str | None
    component: str
    module: str
    state: str
    import_path: tuple[str, ...]
    returncode: int | None
    error: str | None
    dependency_paths: tuple[tuple[str, ...], ...]
    effective_module: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update({
            "provider": "go-mod-why",
            "scope": "package-import-graph",
            "network": "offline",
            # `module` is the logical/required module path queried by Go. A
            # versioned replacement may have a different effective module
            # identity that OSV matched; both are retained rather than swapping
            # the import-query target to the replacement path.
            "queried_module": self.module,
            "replacement_active": bool(
                self.effective_module
                and self.effective_module != self.module
            ),
            # cmd/go's why implementation loads the package graph with
            # imports.AnyTags(). The evidence is therefore intentionally not a
            # statement about the caller's current build-tag configuration.
            "build_constraints": "any-tags",
            "current_build_configuration_reachability": "not-evaluated",
            "test_imports_may_contribute": True,
            "api_reachability": "not-evaluated",
            "runtime_reachability": "not-evaluated",
            "exploitability": "not-established",
            "persisted": False,
            "interpretation": (
                "Go package-import reachability for the required module path in go mod why's "
                "any-build-tag package graph; replacement identity is retained separately, and "
                "this does not establish current-build, API-call, runtime-call, data-flow, or "
                "exploitability reachability"
            ),
        })
        data["import_path"] = list(self.import_path)
        data["dependency_paths"] = [list(path) for path in self.dependency_paths]
        return data


def _query_key(impact: dict[str, Any]) -> tuple[str, str] | None:
    if impact.get("provider") != "go-modules":
        return None
    component = impact.get("component")
    evidence = impact.get("evidence")
    # The logical required module is intentionally the query target. Go replace
    # directives redirect its contents; they do not require application imports
    # to change to the replacement module path.
    module = evidence.get("module") if isinstance(evidence, dict) else None
    if not isinstance(component, str) or not component or not isinstance(module, str) or not module:
        return None
    return component, module


def _query_one(
    graph: ProjectGraph,
    component: str,
    module: str,
    query: Callable[..., tuple[list[NativeWhyResult], list[NativeGraphSkip]]],
) -> tuple[str, tuple[str, ...], int | None, str | None]:
    try:
        results, skips = query(graph, module, selector=component)
    except (OSError, ValueError) as exc:
        return "query-failed", (), None, str(exc)

    matching = [result for result in results if result.component == component]
    if len(matching) == 1:
        result = matching[0]
        if not result.succeeded:
            return "query-failed", (), result.returncode, result.stderr or "go mod why -m failed"
        return (
            "package-import-reachable" if result.needed else "not-package-import-reachable",
            result.path,
            result.returncode,
            result.stderr or None,
        )
    if len(matching) > 1:
        return "query-failed", (), None, "go mod why -m returned multiple results for one component"

    matching_skips = [skip for skip in skips if skip.component == component]
    if matching_skips:
        return "query-failed", (), None, "; ".join(sorted({skip.reason for skip in matching_skips}))
    return "query-failed", (), None, "go mod why -m returned no result for the requested component"


def collect_go_import_reachability(
    graph: ProjectGraph,
    dependency_impacts: list[dict[str, Any]],
    *,
    query: Callable[..., tuple[list[NativeWhyResult], list[NativeGraphSkip]]] = query_native_why_offline,
) -> list[GoImportReachabilityEvidence]:
    """Collect opt-in Go package-import evidence for vulnerable dependency impacts.

    Only impacts already correlated to the native Go module graph are queried.
    Each component/logical-module pair is queried once even when several
    advisories refer to the same package occurrence. `go mod why -m` is executed
    through UPM's GOPROXY=off boundary by default.

    The query target remains the logical required module when a replacement is
    active; the effective replacement identity is retained separately as scan
    identity evidence.

    Go's why implementation evaluates an any-build-tag package graph and can
    include test imports. Accordingly this evidence intentionally stops at that
    package-import graph: it does not claim reachability in the current build
    configuration, that a vulnerable function/API is called, that a runtime path
    reaches it, or that the advisory is exploitable in the selected program.
    """

    cache: dict[tuple[str, str], tuple[str, tuple[str, ...], int | None, str | None]] = {}
    evidence_rows: list[GoImportReachabilityEvidence] = []

    for impact in dependency_impacts:
        key = _query_key(impact)
        if key is None:
            continue
        component, module = key
        if key not in cache:
            cache[key] = _query_one(graph, component, module, query)
        state, import_path, returncode, error = cache[key]

        advisory_id = impact.get("advisory_id")
        package = impact.get("package")
        version = impact.get("version")
        if not isinstance(advisory_id, str) or not isinstance(package, str):
            continue
        impact_evidence = impact.get("evidence")
        effective_module = (
            impact_evidence.get("effective_name")
            if isinstance(impact_evidence, dict)
            and isinstance(impact_evidence.get("effective_name"), str)
            else None
        )
        paths = impact.get("paths")
        dependency_paths = tuple(
            tuple(node for node in path if isinstance(node, str))
            for path in paths
            if isinstance(path, (list, tuple))
        ) if isinstance(paths, (list, tuple)) else ()

        evidence_rows.append(GoImportReachabilityEvidence(
            advisory_id=advisory_id,
            package=package,
            version=version if isinstance(version, str) else None,
            component=component,
            module=module,
            state=state,
            import_path=import_path,
            returncode=returncode,
            error=error,
            dependency_paths=tuple(sorted(set(dependency_paths))),
            effective_module=effective_module,
        ))

    return sorted(evidence_rows, key=lambda item: (
        item.advisory_id,
        item.package,
        item.version or "",
        item.component,
        item.module,
        item.effective_module or "",
        item.state,
        item.import_path,
    ))
