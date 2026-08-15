from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .discovery import discover
from .doctor import diagnose
from .query import normalize_package_name

REGISTRY_VERSION = 1


class RegistryError(ValueError):
    """Raised when the local project registry cannot be read or updated safely."""


def default_registry_path() -> Path:
    return Path.home() / ".upm" / "projects.json"


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path).expanduser().resolve() if path is not None else default_registry_path()
    if not target.is_file():
        return {"version": REGISTRY_VERSION, "projects": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Could not read project registry {target}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != REGISTRY_VERSION or not isinstance(data.get("projects"), list):
        raise RegistryError(f"Unsupported or invalid project registry: {target}")
    return data


def _write_registry(data: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path).expanduser().resolve() if path is not None else default_registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def registered_paths(path: str | Path | None = None) -> list[Path]:
    data = load_registry(path)
    result: list[Path] = []
    for value in data["projects"]:
        if isinstance(value, str):
            result.append(Path(value))
    return sorted(result, key=lambda item: str(item))


def register_project(root: str | Path, path: str | Path | None = None) -> tuple[Path, bool]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise RegistryError(f"Project path is not a directory: {root_path}")
    graph = discover(root_path)
    if not graph.components:
        raise RegistryError(f"No supported project components were discovered under {root_path}")

    data = load_registry(path)
    projects = {value for value in data["projects"] if isinstance(value, str)}
    before = len(projects)
    projects.add(str(root_path))
    data["projects"] = sorted(projects)
    _write_registry(data, path)
    return root_path, len(projects) != before


def unregister_project(root: str | Path, path: str | Path | None = None) -> tuple[Path, bool]:
    root_path = Path(root).expanduser().resolve()
    data = load_registry(path)
    projects = {value for value in data["projects"] if isinstance(value, str)}
    existed = str(root_path) in projects
    projects.discard(str(root_path))
    data["projects"] = sorted(projects)
    _write_registry(data, path)
    return root_path, existed


def project_statuses(path: str | Path | None = None, *, deep: bool = False) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for root in registered_paths(path):
        if not root.is_dir():
            statuses.append({
                "path": str(root),
                "exists": False,
                "components": 0,
                "ecosystems": [],
                "managers": [],
                "direct_dependencies": 0,
                "resolved_packages": 0,
                "health": None,
            })
            continue
        try:
            graph = discover(root)
            report = diagnose(graph, deep=deep)
        except (OSError, ValueError) as exc:
            statuses.append({"path": str(root), "exists": True, "error": str(exc)})
            continue
        statuses.append({
            "path": str(root),
            "exists": True,
            "components": len(graph.components),
            "ecosystems": sorted({component.ecosystem for component in graph.components}),
            "managers": sorted({component.manager for component in graph.components if component.manager}),
            "direct_dependencies": sum(len(component.dependencies) for component in graph.components),
            "resolved_packages": sum(len(component.resolved_packages) for component in graph.components),
            "health": report.to_dict(),
        })
    return statuses


def fleet_inventory(path: str | Path | None = None) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for root in registered_paths(path):
        if not root.is_dir():
            continue
        try:
            graph = discover(root)
        except (OSError, ValueError):
            continue
        for component in graph.components:
            for package in component.resolved_packages:
                inventory.append({
                    "project": str(root),
                    "component": component.key(graph.root),
                    "ecosystem": component.ecosystem,
                    "manager": component.manager,
                    "name": package.name,
                    "normalized_name": normalize_package_name(component.ecosystem, package.name),
                    "version": package.version,
                    "source": package.source,
                    "location": package.location,
                })
    return sorted(inventory, key=lambda item: (
        item["ecosystem"], item["normalized_name"], item["version"], item["project"], item["component"], item["location"] or ""
    ))


def fleet_resolved_duplicates(path: str | Path | None = None) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in fleet_inventory(path):
        key = (item["ecosystem"], item["normalized_name"])
        occurrence = {field: item[field] for field in ("project", "component", "name", "version", "source", "location")}
        groups.setdefault(key, []).append(occurrence)

    result: list[dict[str, Any]] = []
    for (ecosystem, name), occurrences in sorted(groups.items()):
        projects = {item["project"] for item in occurrences}
        versions = {item["version"] for item in occurrences}
        if len(occurrences) < 2 or len(projects) < 2:
            continue
        result.append({
            "ecosystem": ecosystem,
            "name": name,
            "projects": len(projects),
            "occurrences": occurrences,
            "version_divergence": len(versions) > 1,
        })
    return result
