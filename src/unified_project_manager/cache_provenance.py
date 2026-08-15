from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .cargo_cache_provenance import CargoCacheUse, aggregate_cargo_cache_uses, cargo_cache_uses
from .cargo_graph import CargoGraphError, CargoGraphResult, execute_cargo_graph, plan_cargo_graphs
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
    consistent = attributed <= total
    return {
        "manager": manager,
        "scope": "GOMODCACHE" if manager == "go" else "CARGO_HOME registry+git",
        "total_bytes": total,
        "attributed_bytes": attributed,
        "unattributed_bytes": max(total - attributed, 0),
        "coverage_ratio": (attributed / total) if total else None,
        "measurement_consistent": consistent,
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
    ``manifest_path`` under exact ``registry/src`` or ``git/checkouts`` roots.

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

    storage_entries, storage_skips = storage_probe(managers=selected_managers)
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
            try:
                plans = plan_cargo_graphs(graph)
            except (CargoGraphError, OSError, ValueError) as exc:
                provider_failures.append({
                    "manager": "cargo",
                    "project": str(root),
                    "component": None,
                    "returncode": None,
                    "error": str(exc),
                })
                plans = []
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
        and not storage_skips
        and not provider_failures
        and not provider_skips
        and all(report["measurement_consistent"] for report in reports)
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
        "storage_skips": [skip.to_dict() for skip in storage_skips],
        "unattributed_means_unused": False,
        "reclaimable_bytes": None,
        "reclaimable": False,
    }
