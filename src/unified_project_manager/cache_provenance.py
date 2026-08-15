from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .cargo_cache_provenance import CargoCacheUse, aggregate_cargo_cache_uses, cargo_cache_uses
from .cargo_graph import (
    CargoGraphError,
    CargoGraphResult,
    cargo_provider_component_keys,
    execute_cargo_graph,
    plan_cargo_graphs,
)
from .discovery import discover
from .global_storage import GlobalStorageEntry, GlobalStorageSkip, global_cache_storage
from .go_cache_provenance import GoCacheUse, aggregate_go_cache_uses, go_cache_uses
from .go_offline_provider import execute_native_graph_offline
from .native_graph import NativeGraphResult, plan_native_graph
from .registry import registered_paths


SUPPORTED_CACHE_PROVENANCE_MANAGERS = ("go", "cargo")


def _storage_root(
    entries: Iterable[GlobalStorageEntry],
    manager: str,
    category: str,
) -> Path | None:
    matches = [
        Path(entry.path).expanduser().resolve()
        for entry in entries
        if entry.manager == manager and entry.category == category
    ]
    return matches[0] if len(matches) == 1 else None


def _manager_total(entries: Iterable[GlobalStorageEntry], manager: str) -> int:
    if manager == "go":
        categories = {"module-cache"}
    elif manager == "cargo":
        categories = {"registry-cache", "git-cache"}
    else:
        return 0
    return sum(
        entry.bytes
        for entry in entries
        if entry.manager == manager and entry.category in categories
    )


def _group_identities(manager: str, group: object) -> set[str]:
    if manager == "cargo":
        values = getattr(group, "identities", None)
        if isinstance(values, tuple):
            return {value for value in values if isinstance(value, str) and value}
    value = getattr(group, "purl", None)
    if isinstance(value, str) and value:
        return {value}
    return {"(unknown)"}


def _identity_conflicts(manager: str, groups: list[object]) -> list[dict[str, Any]]:
    by_path: dict[str, list[tuple[str, set[str]]]] = {}
    for group in groups:
        path = getattr(group, "path", None)
        if not isinstance(path, str) or not path:
            continue
        cache_kind = getattr(group, "cache_kind", "unknown")
        by_path.setdefault(path, []).append((
            cache_kind if isinstance(cache_kind, str) else "unknown",
            _group_identities(manager, group),
        ))

    conflicts: list[dict[str, Any]] = []
    for path, records in sorted(by_path.items()):
        identities = set().union(*(values for _kind, values in records))
        if manager == "cargo":
            registry_records = [values for kind, values in records if kind == "registry-source"]
            if any(len(values) > 1 for values in registry_records):
                conflicts.append({
                    "path": path,
                    "identities": sorted(identities),
                    "reason": "one Cargo registry source object mapped to multiple package identities",
                })
                continue
        signatures = {(kind, tuple(sorted(values))) for kind, values in records}
        if len(signatures) > 1:
            conflicts.append({
                "path": path,
                "identities": sorted(identities),
                "reason": "one physical path was emitted as multiple incompatible cache groups",
            })
    return conflicts


def _manager_report(
    manager: str,
    entries: list[GlobalStorageEntry],
    groups: list[object],
) -> dict[str, Any]:
    total = _manager_total(entries, manager)
    attributed = sum(
        value
        for group in groups
        if isinstance((value := getattr(group, "bytes", None)), int)
    )
    conflicts = _identity_conflicts(manager, groups)
    return {
        "manager": manager,
        "scope": "GOMODCACHE" if manager == "go" else "CARGO_HOME registry+git",
        "total_bytes": total,
        "attributed_bytes": attributed,
        "unattributed_bytes": max(total - attributed, 0),
        "coverage_ratio": (attributed / total) if total else None,
        "measurement_consistent": attributed <= total,
        "identity_consistent": not conflicts,
        "identity_conflicts": conflicts,
        "groups": [group.to_dict() for group in groups],
        "unattributed_means_unused": False,
        "reclaimable_bytes": None,
        "reclaimable": False,
    }


def collect_cache_provenance(
    registry: str | Path | None = None,
    *,
    roots: Iterable[str | Path] | None = None,
    managers: Iterable[str] = SUPPORTED_CACHE_PROVENANCE_MANAGERS,
    closed_universe: bool = False,
    storage_probe: Callable[..., tuple[list[GlobalStorageEntry], list[GlobalStorageSkip]]] = global_cache_storage,
    execute_go: Callable[[object], NativeGraphResult] = execute_native_graph_offline,
    execute_cargo: Callable[[object], CargoGraphResult] = execute_cargo_graph,
) -> dict[str, Any]:
    """Collect read-only physical cache attribution for registered projects.

    Only providers with native physical source identity are supported. Go uses
    native-reported selected module directories (plus matching selected-version
    download artifacts derived from those physical paths). Cargo uses
    ``manifest_path`` to identify canonical registry source objects or git
    checkout worktrees below CARGO_HOME.

    The report deliberately makes no unused/reclaimable inference.
    """

    selected_managers = tuple(dict.fromkeys(managers))
    unsupported = [manager for manager in selected_managers if manager not in SUPPORTED_CACHE_PROVENANCE_MANAGERS]
    if unsupported:
        raise ValueError(f"Unsupported cache provenance manager(s): {', '.join(unsupported)}")

    selected_roots = (
        [Path(value).expanduser().resolve() for value in roots]
        if roots is not None
        else [Path(value).expanduser().resolve() for value in registered_paths(registry)]
    )
    selected_roots = sorted(dict.fromkeys(selected_roots), key=str)

    missing: list[str] = []
    discovery_failures: list[dict[str, str]] = []
    graphs: list[tuple[Path, object]] = []
    for root in selected_roots:
        if not root.is_dir():
            missing.append(str(root))
            continue
        try:
            graphs.append((root, discover(root)))
        except (OSError, ValueError) as exc:
            discovery_failures.append({"project": str(root), "error": str(exc)})

    storage_entries, raw_storage_skips = storage_probe(managers=selected_managers)
    storage_skip_objects = list(raw_storage_skips)
    provider_failures: list[dict[str, Any]] = []
    provider_skips: list[dict[str, Any]] = []
    attribution_skips: list[dict[str, Any]] = []
    go_uses_all: list[GoCacheUse] = []
    cargo_uses_all: list[CargoCacheUse] = []

    go_modcache = _storage_root(storage_entries, "go", "module-cache") if "go" in selected_managers else None
    cargo_registry = _storage_root(storage_entries, "cargo", "registry-cache") if "cargo" in selected_managers else None
    cargo_git = _storage_root(storage_entries, "cargo", "git-cache") if "cargo" in selected_managers else None
    cargo_home = None
    if cargo_registry is not None and cargo_git is not None and cargo_registry.parent == cargo_git.parent:
        cargo_home = cargo_registry.parent

    existing_storage_skip_managers = {skip.manager for skip in storage_skip_objects}
    if "go" in selected_managers and go_modcache is None and "go" not in existing_storage_skip_managers:
        storage_skip_objects.append(GlobalStorageSkip("go", "measured GOMODCACHE root is unavailable or ambiguous"))
    if "cargo" in selected_managers and cargo_home is None and "cargo" not in existing_storage_skip_managers:
        storage_skip_objects.append(GlobalStorageSkip("cargo", "measured Cargo registry/git roots do not identify one CARGO_HOME"))

    for root, graph in graphs:
        if "go" in selected_managers and go_modcache is not None:
            plans, skips = plan_native_graph(graph)
            for skip in skips:
                if skip.ecosystem == "go":
                    provider_skips.append({"manager": "go", "project": str(root), **skip.to_dict()})
            for plan in plans:
                result = execute_go(plan)
                if not result.succeeded:
                    provider_failures.append({
                        "manager": "go",
                        "project": str(root),
                        "component": plan.component,
                        "returncode": result.returncode,
                        "error": result.stderr,
                    })
                    continue
                uses, skips = go_cache_uses(root, [result], go_modcache)
                go_uses_all.extend(uses)
                attribution_skips.extend({"manager": "go", "project": str(root), **item} for item in skips)

        if "cargo" in selected_managers and cargo_home is not None:
            cargo_component_keys = {
                component.key(graph.root)
                for component in graph.components
                if component.ecosystem == "rust" and component.manager == "cargo"
            }
            try:
                plans = plan_cargo_graphs(graph)
                covered = cargo_provider_component_keys(graph, plans)
            except (CargoGraphError, OSError, ValueError) as exc:
                provider_failures.append({
                    "manager": "cargo",
                    "project": str(root),
                    "component": None,
                    "returncode": None,
                    "error": str(exc),
                })
                plans = []
                covered = set()
            for component_key in sorted(cargo_component_keys - covered):
                provider_skips.append({
                    "manager": "cargo",
                    "project": str(root),
                    "component": component_key,
                    "ecosystem": "rust",
                    "reason": "authoritative Cargo cache provenance requires a locked Cargo provider plan",
                })
            for plan in plans:
                result = execute_cargo(plan)
                if not result.succeeded:
                    provider_failures.append({
                        "manager": "cargo",
                        "project": str(root),
                        "component": plan.component,
                        "returncode": result.returncode,
                        "error": result.stderr,
                    })
                    continue
                uses, skips = cargo_cache_uses(root, [result], cargo_home)
                cargo_uses_all.extend(uses)
                attribution_skips.extend({"manager": "cargo", "project": str(root), **item} for item in skips)

    go_groups = aggregate_go_cache_uses(go_uses_all, measure=True) if "go" in selected_managers else []
    cargo_groups = aggregate_cargo_cache_uses(cargo_uses_all, measure=True) if "cargo" in selected_managers else []
    groups_by_manager = {"go": go_groups, "cargo": cargo_groups}
    reports = [
        _manager_report(manager, storage_entries, groups_by_manager.get(manager, []))
        for manager in selected_managers
    ]

    closure_valid = closed_universe and not missing and not discovery_failures
    observation_complete = (
        not missing
        and not discovery_failures
        and not storage_skip_objects
        and not provider_failures
        and not provider_skips
        and all(report["measurement_consistent"] and report["identity_consistent"] for report in reports)
        and (
            ("go" not in selected_managers or go_modcache is not None)
            and ("cargo" not in selected_managers or cargo_home is not None)
        )
    )

    return {
        "scope": "registered-project-cache-provenance",
        "managers": reports,
        "project_universe": {
            "registered": len(selected_roots),
            "observed": len(graphs),
            "missing": missing,
            "discovery_failures": discovery_failures,
            "closed_asserted": bool(closed_universe),
            "closed": closure_valid,
        },
        "observation_complete": observation_complete,
        "provider_failures": provider_failures,
        "provider_skips": provider_skips,
        "attribution_skips": attribution_skips,
        "storage_skips": [skip.to_dict() for skip in storage_skip_objects],
        "unattributed_means_unused": False,
        "reclaimable_bytes": None,
        "reclaimable": False,
    }
