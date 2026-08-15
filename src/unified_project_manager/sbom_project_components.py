from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import Component, ProjectGraph


def _digest_identity(kind: str, values: list[str]) -> str:
    payload = "\0".join((kind, *values))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_component_ref(graph: ProjectGraph, component: Component) -> str:
    """Return a clone-location-independent CycloneDX ref for one UPM component."""
    key = component.key(graph.root)
    digest = _digest_identity("upm-project-component-v1", [key, component.ecosystem, component.manager or ""])
    return f"urn:upm:project-component:sha256:{digest}"


def aggregate_project_ref(graph: ProjectGraph) -> str:
    """Return a deterministic aggregate ref derived from relative component identity."""
    identities = sorted(
        f"{component.key(graph.root)}\0{component.manager or ''}"
        for component in graph.components
    )
    digest = _digest_identity("upm-project-root-v1", identities)
    return f"urn:upm:project-root:sha256:{digest}"


def _component_name(graph: ProjectGraph, component: Component) -> str:
    name = component.metadata.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    path = component.relative_path(graph.root)
    if path == ".":
        return f"root-{component.ecosystem}"
    return f"{path}-{component.ecosystem}"


def _properties(graph: ProjectGraph, component: Component) -> list[dict[str, str]]:
    values = [
        {"name": "upm:role", "value": "project-component"},
        {"name": "upm:component-key", "value": component.key(graph.root)},
        {"name": "upm:ecosystem", "value": component.ecosystem},
        {"name": "upm:path", "value": component.relative_path(graph.root)},
    ]
    if component.manager:
        values.append({"name": "upm:manager", "value": component.manager})
    return sorted(values, key=lambda item: (item["name"], item["value"]))


def cyclonedx_project_component(graph: ProjectGraph, component: Component) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "application",
        "name": _component_name(graph, component),
        "bom-ref": project_component_ref(graph, component),
        "properties": _properties(graph, component),
    }
    version = component.metadata.get("version")
    if isinstance(version, str) and version:
        entry["version"] = version
    return entry


def add_cyclonedx_project_anchors(document: dict[str, Any], graph: ProjectGraph) -> dict[str, Any]:
    """Add an aggregate root plus one application anchor per discovered component.

    Anchors describe project topology only. They intentionally do not infer
    component-to-package dependency edges; provider-specific code may add such
    edges later only when native evidence supports them.
    """
    anchors = [
        cyclonedx_project_component(graph, component)
        for component in graph.components
    ]
    anchors.sort(key=lambda item: item["bom-ref"])
    aggregate_ref = aggregate_project_ref(graph)
    aggregate: dict[str, Any] = {
        "type": "application",
        "name": graph.root.name or "project",
        "bom-ref": aggregate_ref,
        "properties": [
            {"name": "upm:role", "value": "aggregate-project-root"},
            {"name": "upm:component-count", "value": str(len(anchors))},
        ],
    }
    metadata = document.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["component"] = aggregate

    existing = {
        entry.get("bom-ref"): entry
        for entry in document.get("components", [])
        if isinstance(entry, dict) and isinstance(entry.get("bom-ref"), str)
    }
    for anchor in anchors:
        existing.setdefault(anchor["bom-ref"], anchor)
    document["components"] = [existing[ref] for ref in sorted(existing)]

    dependency_sets: dict[str, set[str]] = {}
    for item in document.get("dependencies", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        dependency_sets[item["ref"]] = {
            value for value in item.get("dependsOn", []) if isinstance(value, str)
        }
    if anchors:
        dependency_sets.setdefault(aggregate_ref, set()).update(anchor["bom-ref"] for anchor in anchors)
    if dependency_sets:
        document["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(values)}
            for ref, values in sorted(dependency_sets.items())
        ]
    return document


def _spdx_ref(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"SPDXRef-Package-{digest}"


def aggregate_spdx_id(graph: ProjectGraph) -> str:
    return _spdx_ref(aggregate_project_ref(graph))


def project_component_spdx_id(graph: ProjectGraph, component: Component) -> str:
    return _spdx_ref(project_component_ref(graph, component))


def _spdx_application(
    spdx_id: str,
    name: str,
    *,
    version: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "SPDXID": spdx_id,
        "name": name,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "APPLICATION",
    }
    if version:
        entry["versionInfo"] = version
    if comment:
        entry["comment"] = comment
    return entry


def add_spdx_project_anchors(document: dict[str, Any], graph: ProjectGraph) -> dict[str, Any]:
    """Add SPDX APPLICATION packages mirroring CycloneDX project anchors."""
    packages = {
        entry.get("SPDXID"): entry
        for entry in document.get("packages", [])
        if isinstance(entry, dict) and isinstance(entry.get("SPDXID"), str)
    }
    aggregate_id = aggregate_spdx_id(graph)
    packages.setdefault(
        aggregate_id,
        _spdx_application(
            aggregate_id,
            graph.root.name or "project",
            comment=f"UPM aggregate project root containing {len(graph.components)} discovered component(s).",
        ),
    )

    component_ids: list[str] = []
    for component in graph.components:
        spdx_id = project_component_spdx_id(graph, component)
        component_ids.append(spdx_id)
        version = component.metadata.get("version")
        packages.setdefault(
            spdx_id,
            _spdx_application(
                spdx_id,
                _component_name(graph, component),
                version=version if isinstance(version, str) and version else None,
                comment=(
                    f"UPM project component {component.key(graph.root)}; "
                    f"ecosystem={component.ecosystem}; manager={component.manager or 'unknown'}; "
                    f"path={component.relative_path(graph.root)}"
                ),
            ),
        )

    relationships: set[tuple[str, str, str]] = set()
    for item in document.get("relationships", []):
        if not isinstance(item, dict):
            continue
        source = item.get("spdxElementId")
        kind = item.get("relationshipType")
        target = item.get("relatedSpdxElement")
        if all(isinstance(value, str) for value in (source, kind, target)):
            relationships.add((source, kind, target))
    for component_id in component_ids:
        relationships.add((aggregate_id, "CONTAINS", component_id))
    for spdx_id in packages:
        relationships.add(("SPDXRef-DOCUMENT", "DESCRIBES", spdx_id))

    package_list = [packages[key] for key in sorted(packages)]
    relationship_list = [
        {"spdxElementId": source, "relationshipType": kind, "relatedSpdxElement": target}
        for source, kind, target in sorted(relationships)
    ]
    document["packages"] = package_list
    document["relationships"] = relationship_list

    digest = hashlib.sha256(json.dumps(
        {"packages": package_list, "relationships": relationship_list},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    document["documentNamespace"] = f"https://spdx.org/spdxdocs/upm-{digest}"
    return document
