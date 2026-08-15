from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict, deque
from typing import Any

from .python_lock_graph import PythonLockGraphResult
from .sbom import purl_for


def python_lock_scope_ids(result: PythonLockGraphResult) -> set[str]:
    if not result.succeeded:
        return set()
    packages = {package.package_id: package for package in result.packages}
    forward: dict[str, set[str]] = defaultdict(set)
    for edge in result.edges:
        if edge.target_id and edge.source_id in {*packages, *result.project_roots}:
            forward[edge.source_id].add(edge.target_id)
    reachable: set[str] = set()
    queue = deque(result.project_roots)
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for child in sorted(forward.get(current, set())):
            if child in packages:
                reachable.add(child)
            queue.append(child)
    return reachable


def _registry_purl(package: object) -> str | None:
    if getattr(package, "source_kind", None) != "registry":
        return None
    name = getattr(package, "name", None)
    version = getattr(package, "version", None)
    if not isinstance(name, str) or not isinstance(version, str) or not version:
        return None
    try:
        return purl_for("python", name, version)
    except ValueError:
        return None


def _add_property(entry: dict[str, Any], name: str, value: str) -> None:
    properties = entry.setdefault("properties", [])
    item = {"name": name, "value": value}
    if item not in properties:
        properties.append(item)
    properties.sort(key=lambda item: (item.get("name", ""), item.get("value", "")))


def merge_python_lock_cyclonedx(base: dict[str, Any], results: list[PythonLockGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    components: dict[str, dict[str, Any]] = {
        entry["bom-ref"]: entry
        for entry in merged.get("components", [])
        if isinstance(entry, dict) and isinstance(entry.get("bom-ref"), str)
    }
    dependency_sets: dict[str, set[str]] = {}
    for item in merged.get("dependencies", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        dependency_sets[item["ref"]] = {
            value for value in item.get("dependsOn", []) if isinstance(value, str)
        }

    for result in results:
        if not result.succeeded:
            continue
        allowed = python_lock_scope_ids(result)
        refs: dict[str, str] = {}
        conditional_omitted: dict[str, int] = defaultdict(int)
        ambiguous_omitted: dict[str, int] = defaultdict(int)
        for package in result.packages:
            if package.package_id not in allowed:
                continue
            purl = _registry_purl(package)
            if purl is None:
                continue
            refs[package.package_id] = purl
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
            _add_property(entry, f"upm:{result.plan.manager}:identity-kind", "structured-lock")
            if package.groups:
                _add_property(entry, f"upm:{result.plan.manager}:groups", ",".join(package.groups))

        for edge in result.edges:
            source = refs.get(edge.source_id)
            if not source:
                continue
            target = refs.get(edge.target_id or "")
            if edge.ambiguous or not target:
                ambiguous_omitted[source] += 1
                continue
            if edge.marker:
                conditional_omitted[source] += 1
                continue
            if source != target:
                dependency_sets.setdefault(source, set()).add(target)
        for ref, count in conditional_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:conditional-edges-omitted", str(count))
        for ref, count in ambiguous_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:ambiguous-edges-omitted", str(count))

    merged["components"] = [components[ref] for ref in sorted(components)]
    if dependency_sets:
        merged["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(values)}
            for ref, values in sorted(dependency_sets.items())
            if values
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


def merge_python_lock_spdx(base: dict[str, Any], results: list[PythonLockGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    packages: dict[str, dict[str, Any]] = {
        entry["SPDXID"]: entry
        for entry in merged.get("packages", [])
        if isinstance(entry, dict) and isinstance(entry.get("SPDXID"), str)
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
        allowed = python_lock_scope_ids(result)
        refs: dict[str, str] = {}
        for package in result.packages:
            if package.package_id not in allowed:
                continue
            purl = _registry_purl(package)
            if purl is None:
                continue
            spdx_id = _spdx_id(purl)
            refs[package.package_id] = spdx_id
            packages.setdefault(spdx_id, _spdx_package(package.name, package.version, purl))

        for edge in result.edges:
            if edge.ambiguous or edge.marker:
                continue
            source = refs.get(edge.source_id)
            target = refs.get(edge.target_id or "")
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
