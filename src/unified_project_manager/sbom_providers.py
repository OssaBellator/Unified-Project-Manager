from __future__ import annotations

from typing import Any

from .models import ProjectGraph
from .sbom import cyclonedx_bom_with_native, purl_for


def _add_property(entry: dict[str, Any], name: str, value: str) -> None:
    properties = entry.setdefault("properties", [])
    item = {"name": name, "value": value}
    if item not in properties:
        properties.append(item)


def cyclonedx_bom_with_providers(
    graph: ProjectGraph,
    *,
    go_results: list[object] | None = None,
    npm_results: list[object] | None = None,
    cargo_results: list[object] | None = None,
) -> dict[str, Any]:
    """Enrich a CycloneDX BOM with authoritative provider relationships.

    Go selected-module results may add concrete components and relationships.
    npm/Cargo graph results add relationships only when endpoint identities were
    already supported by static native provenance (for example a registry PURL).
    """
    bom = cyclonedx_bom_with_native(graph, go_results or [])
    components = {
        entry.get("bom-ref"): entry
        for entry in bom.get("components", [])
        if isinstance(entry, dict) and isinstance(entry.get("bom-ref"), str)
    }
    dependency_sets: dict[str, set[str]] = {}
    for dependency in bom.get("dependencies", []):
        if not isinstance(dependency, dict) or not isinstance(dependency.get("ref"), str):
            continue
        dependency_sets[dependency["ref"]] = {
            value for value in dependency.get("dependsOn", []) if isinstance(value, str)
        }

    for result in npm_results or []:
        if not getattr(result, "succeeded", False):
            continue
        occurrence_refs: dict[str, str] = {}
        occurrence_counts: dict[str, int] = {}
        direct_counts: dict[str, int] = {}
        for package in getattr(result, "packages", []):
            name = getattr(package, "name", None)
            version = getattr(package, "version", None)
            logical_ref = getattr(package, "ref", None)
            if not isinstance(name, str) or not isinstance(version, str) or not isinstance(logical_ref, str):
                continue
            try:
                purl = purl_for("node", name, version)
            except ValueError:
                continue
            if purl not in components:
                continue
            occurrence_refs[logical_ref] = purl
            occurrence_counts[purl] = occurrence_counts.get(purl, 0) + 1
            if getattr(package, "direct", False):
                direct_counts[purl] = direct_counts.get(purl, 0) + 1

        for edge in getattr(result, "edges", []):
            source = occurrence_refs.get(getattr(edge, "source_ref", ""))
            target = occurrence_refs.get(getattr(edge, "target_ref", ""))
            if source and target and source != target:
                dependency_sets.setdefault(source, set()).add(target)

        for ref, count in occurrence_counts.items():
            entry = components[ref]
            _add_property(entry, "upm:npm:identity-kind", "package-lock+logical-tree")
            _add_property(entry, "upm:npm:logical-occurrences", str(count))
            if direct_counts.get(ref):
                _add_property(entry, "upm:npm:direct-occurrences", str(direct_counts[ref]))

    for result in cargo_results or []:
        if not getattr(result, "succeeded", False):
            continue
        package_refs: dict[str, str] = {}
        for package in getattr(result, "packages", []):
            package_id = getattr(package, "package_id", None)
            name = getattr(package, "name", None)
            version = getattr(package, "version", None)
            source = getattr(package, "source", None)
            if not all(isinstance(value, str) and value for value in (package_id, name, version)):
                continue
            if not isinstance(source, str) or not source.startswith("registry+"):
                continue
            try:
                purl = purl_for("rust", name, version)
            except ValueError:
                continue
            if purl not in components:
                continue
            package_refs[package_id] = purl
            _add_property(components[purl], "upm:cargo:identity-kind", "cargo-lock+offline-metadata")

        for edge in getattr(result, "edges", []):
            source = package_refs.get(getattr(edge, "source_id", ""))
            target = package_refs.get(getattr(edge, "target_id", ""))
            if source and target and source != target:
                dependency_sets.setdefault(source, set()).add(target)

    for entry in components.values():
        properties = entry.get("properties")
        if isinstance(properties, list):
            properties.sort(key=lambda item: (item.get("name", ""), item.get("value", "")))

    bom["components"] = [components[ref] for ref in sorted(components)]
    if dependency_sets:
        bom["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(values)}
            for ref, values in sorted(dependency_sets.items())
            if values
        ]
    else:
        bom.pop("dependencies", None)
    return bom
