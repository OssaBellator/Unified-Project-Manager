from __future__ import annotations

from typing import Any

from .models import ProjectGraph
from .sbom import cyclonedx_bom_with_native, purl_for


def cyclonedx_bom_with_providers(
    graph: ProjectGraph,
    *,
    go_results: list[object] | None = None,
    npm_results: list[object] | None = None,
) -> dict[str, Any]:
    """Enrich a CycloneDX BOM with authoritative provider relationships.

    Go selected-module results may add concrete components and relationships.
    npm logical-tree results add relationships only when both endpoints already
    have trustworthy Package URL identities in the static package-lock inventory.
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
                # npm ls proves logical placement/version, but not registry provenance.
                # Do not create a registry identity that static native state did not support.
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
            properties = entry.setdefault("properties", [])
            values = [
                {"name": "upm:npm:identity-kind", "value": "package-lock+logical-tree"},
                {"name": "upm:npm:logical-occurrences", "value": str(count)},
            ]
            if direct_counts.get(ref):
                values.append({"name": "upm:npm:direct-occurrences", "value": str(direct_counts[ref])})
            for value in values:
                if value not in properties:
                    properties.append(value)
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
