from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from typing import Any

from .sbom import purl_for
from .yarn_graph import YarnGraphResult


def _add_property(entry: dict[str, Any], name: str, value: str) -> None:
    properties = entry.setdefault("properties", [])
    if not isinstance(properties, list):
        properties = []
        entry["properties"] = properties
    item = {"name": name, "value": value}
    if item not in properties:
        properties.append(item)
    properties.sort(key=lambda value: (str(value.get("name", "")), str(value.get("value", ""))))


def _registry_purl(package: object) -> str | None:
    protocol = getattr(package, "protocol", None)
    name = getattr(package, "name", None)
    version = getattr(package, "version", None)
    if protocol != "npm" or not isinstance(name, str) or not isinstance(version, str) or not version:
        return None
    try:
        return purl_for("node", name, version)
    except ValueError:
        return None


def merge_yarn_cyclonedx(base: dict[str, Any], results: list[YarnGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    components: dict[str, dict[str, Any]] = {
        item["bom-ref"]: item
        for item in merged.get("components", [])
        if isinstance(item, dict) and isinstance(item.get("bom-ref"), str)
    }
    dependencies: dict[str, set[str]] = {}
    for item in merged.get("dependencies", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        dependencies.setdefault(item["ref"], set()).update(
            target for target in item.get("dependsOn", []) if isinstance(target, str)
        )

    for result in results:
        if not result.succeeded:
            continue
        locator_refs: dict[str, str] = {}
        occurrence_sets: dict[str, set[str]] = defaultdict(set)
        virtual_counts: dict[str, int] = defaultdict(int)
        package_by_locator = {package.locator: package for package in result.packages}

        for package in result.packages:
            purl = _registry_purl(package)
            if purl is None:
                continue
            locator_refs[package.locator] = purl
            occurrence_sets[purl].add(package.locator)
            if package.virtual:
                virtual_counts[purl] += 1
            entry = components.get(purl)
            if entry is None:
                entry = {
                    "type": "library",
                    "name": package.name,
                    "version": package.version,
                    "bom-ref": purl,
                    "purl": purl,
                }
                components[purl] = entry
            _add_property(entry, "upm:yarn:identity-kind", "berry-npm-resolution")
            if result.yarn_version:
                _add_property(entry, "upm:yarn:version", result.yarn_version)
            if result.plan.selected_component:
                _add_property(entry, "upm:yarn:scope-component", result.plan.selected_component)

        for purl, locators in occurrence_sets.items():
            entry = components[purl]
            _add_property(entry, "upm:yarn:locator-occurrences", str(len(locators)))
            if virtual_counts[purl]:
                _add_property(entry, "upm:yarn:virtual-occurrences", str(virtual_counts[purl]))

        for edge in result.edges:
            source = locator_refs.get(edge.source_locator)
            target = locator_refs.get(edge.target_locator)
            if source and target and source != target:
                dependencies.setdefault(source, set()).add(target)

        # Preserve an observation that npm-protocol packages existed behind
        # workspace/local roots without inventing a project-root PURL edge.
        for edge in result.edges:
            if edge.target_locator not in locator_refs:
                continue
            if edge.source_locator in locator_refs:
                continue
            source_package = package_by_locator.get(edge.source_locator)
            if source_package is not None and source_package.project_member:
                _add_property(
                    components[locator_refs[edge.target_locator]],
                    "upm:yarn:reachable-from-workspace",
                    source_package.name,
                )

    merged["components"] = [components[ref] for ref in sorted(components)]
    if dependencies:
        merged["dependencies"] = [
            {"ref": source, "dependsOn": sorted(targets)}
            for source, targets in sorted(dependencies.items())
            if targets
        ]
    else:
        merged.pop("dependencies", None)
    return merged


def _spdx_id(identity: str) -> str:
    return f"SPDXRef-Package-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _spdx_package(name: str, version: str, purl: str) -> dict[str, Any]:
    return {
        "SPDXID": _spdx_id(purl),
        "name": name,
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "LIBRARY",
        "externalRefs": [{
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": purl,
        }],
    }


def merge_yarn_spdx(base: dict[str, Any], results: list[YarnGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    packages: dict[str, dict[str, Any]] = {
        item["SPDXID"]: item
        for item in merged.get("packages", [])
        if isinstance(item, dict) and isinstance(item.get("SPDXID"), str)
    }
    relationships: set[tuple[str, str, str]] = set()
    for item in merged.get("relationships", []):
        if not isinstance(item, dict):
            continue
        source = item.get("spdxElementId")
        kind = item.get("relationshipType")
        target = item.get("relatedSpdxElement")
        if all(isinstance(value, str) for value in (source, kind, target)):
            relationships.add((source, kind, target))

    for result in results:
        if not result.succeeded:
            continue
        locator_refs: dict[str, str] = {}
        for package in result.packages:
            purl = _registry_purl(package)
            if purl is None or package.version is None:
                continue
            spdx_id = _spdx_id(purl)
            locator_refs[package.locator] = spdx_id
            packages.setdefault(spdx_id, _spdx_package(package.name, package.version, purl))

        for edge in result.edges:
            source = locator_refs.get(edge.source_locator)
            target = locator_refs.get(edge.target_locator)
            if source and target and source != target:
                relationships.add((source, "DEPENDS_ON", target))

    relationships = {
        relation for relation in relationships
        if relation[1] != "DESCRIBES" or relation[0] != "SPDXRef-DOCUMENT"
    }
    for package_id in packages:
        relationships.add(("SPDXRef-DOCUMENT", "DESCRIBES", package_id))

    package_list = [packages[key] for key in sorted(packages)]
    relationship_list = [
        {"spdxElementId": source, "relationshipType": kind, "relatedSpdxElement": target}
        for source, kind, target in sorted(relationships)
    ]
    merged["packages"] = package_list
    merged["relationships"] = relationship_list
    digest = hashlib.sha256(json.dumps(
        {"packages": package_list, "relationships": relationship_list},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    merged["documentNamespace"] = f"https://spdx.org/spdxdocs/upm-{digest}"
    return merged
