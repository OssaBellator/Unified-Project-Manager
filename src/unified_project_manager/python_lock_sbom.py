from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict, deque
from typing import Any

from .python_lock_graph import PythonLockGraphResult
from .sbom import purl_for


_UNCONDITIONAL = "unconditional"
_CONDITIONAL = "conditional"
_POSSIBLE = "possible"


def _edge_is_conditional(edge: object) -> bool:
    if bool(getattr(edge, "optional", False)):
        return True
    marker = getattr(edge, "marker", None)
    if isinstance(marker, str) and marker.strip():
        return True
    requirement = getattr(edge, "requirement", None)
    return isinstance(requirement, str) and ";" in requirement and bool(requirement.partition(";")[2].strip())


def _python_lock_reachability_states(
    result: PythonLockGraphResult,
) -> tuple[set[str], set[str], set[str]]:
    """Return admitted, conditional-only, and ambiguity-possible package ids.

    Resolved edges are traversed from synthetic project roots. Marker/optional
    conditions propagate a conditional state. Reachable ambiguous references do
    not become fake resolved edges, but all of their candidate package ids are
    admitted as *possible* scan inventory and that uncertainty propagates through
    each candidate's own dependency records.
    """

    if not result.succeeded:
        return set(), set(), set()

    packages = {package.package_id: package for package in result.packages}
    outgoing: dict[str, list[object]] = defaultdict(list)
    for edge in result.edges:
        outgoing[edge.source_id].append(edge)
    for source in outgoing:
        outgoing[source].sort(key=lambda edge: (
            getattr(edge, "dependency_name", ""),
            getattr(edge, "target_id", "") or "",
            tuple(getattr(edge, "candidate_ids", ()) or ()),
        ))

    states: dict[str, set[str]] = defaultdict(set)
    queue: deque[tuple[str, str]] = deque(
        (root, _UNCONDITIONAL) for root in result.project_roots
    )
    visited: set[tuple[str, str]] = set()

    while queue:
        current, state = queue.popleft()
        key = (current, state)
        if key in visited:
            continue
        visited.add(key)
        if current in packages:
            states[current].add(state)

        for edge in outgoing.get(current, []):
            target_id = getattr(edge, "target_id", None)
            if isinstance(target_id, str) and target_id:
                if state == _POSSIBLE:
                    next_state = _POSSIBLE
                elif state == _CONDITIONAL or _edge_is_conditional(edge):
                    next_state = _CONDITIONAL
                else:
                    next_state = _UNCONDITIONAL
                queue.append((target_id, next_state))
                continue

            if bool(getattr(edge, "ambiguous", False)):
                for candidate in getattr(edge, "candidate_ids", ()) or ():
                    if isinstance(candidate, str) and candidate in packages:
                        queue.append((candidate, _POSSIBLE))

    admitted = set(states)
    conditional_only = {
        package_id
        for package_id, values in states.items()
        if _UNCONDITIONAL not in values and _CONDITIONAL in values
    }
    possible_only = {
        package_id
        for package_id, values in states.items()
        if values == {_POSSIBLE}
    }
    return admitted, conditional_only, possible_only


def python_lock_scope_ids(result: PythonLockGraphResult) -> set[str]:
    admitted, _conditional, _possible = _python_lock_reachability_states(result)
    return admitted


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


def _add_occurrence(entry: dict[str, Any], location: str) -> None:
    evidence = entry.setdefault("evidence", {})
    occurrences = evidence.setdefault("occurrences", [])
    item = {"location": location}
    if item not in occurrences:
        occurrences.append(item)
    occurrences.sort(key=lambda item: item.get("location", ""))


def _result_registry_purls(results: list[PythonLockGraphResult]) -> set[str]:
    return {
        purl
        for result in results
        if result.succeeded
        for package in result.packages
        if (purl := _registry_purl(package)) is not None
    }


def _provider_occurrence_locations(results: list[PythonLockGraphResult]) -> set[str]:
    return {
        f"{result.plan.component}:{result.plan.lockfile.name}"
        for result in results
        if result.succeeded
    }


def _strip_python_lock_cyclonedx_seed(
    merged: dict[str, Any],
    results: list[PythonLockGraphResult],
) -> None:
    """Remove broad adapter observations owned by structured lock providers.

    CycloneDX static inventory carries occurrence locations, so provider-owned
    lockfile occurrences can be removed without discarding the same PURL if an
    unrelated component independently observed it. Entries without occurrence
    evidence use a conservative compatibility fallback and are removed only when
    their PURL belongs to one of the supplied structured lock results.
    """

    provider_purls = _result_registry_purls(results)
    provider_locations = _provider_occurrence_locations(results)
    kept: list[dict[str, Any]] = []
    for entry in merged.get("components", []):
        if not isinstance(entry, dict):
            continue
        purl = entry.get("purl")
        if not isinstance(purl, str) or purl not in provider_purls:
            kept.append(entry)
            continue
        evidence = entry.get("evidence")
        occurrences = evidence.get("occurrences") if isinstance(evidence, dict) else None
        if not isinstance(occurrences, list):
            continue
        retained = [
            occurrence
            for occurrence in occurrences
            if not (
                isinstance(occurrence, dict)
                and isinstance(occurrence.get("location"), str)
                and occurrence["location"] in provider_locations
            )
        ]
        if retained:
            replacement = copy.deepcopy(entry)
            replacement.setdefault("evidence", {})["occurrences"] = retained
            kept.append(replacement)
    merged["components"] = kept


def merge_python_lock_cyclonedx(base: dict[str, Any], results: list[PythonLockGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    _strip_python_lock_cyclonedx_seed(merged, results)
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
        allowed, conditional_only, possible_only = _python_lock_reachability_states(result)
        package_by_id = {package.package_id: package for package in result.packages}
        refs: dict[str, str] = {}
        conditional_omitted: dict[str, int] = defaultdict(int)
        ambiguous_omitted: dict[str, int] = defaultdict(int)
        unresolved_omitted: dict[str, int] = defaultdict(int)
        non_registry_omitted: dict[str, int] = defaultdict(int)
        occurrence = f"{result.plan.component}:{result.plan.lockfile.name}"

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
            if package.package_id in conditional_only:
                _add_property(entry, f"upm:{result.plan.manager}:conditional-reachability", "true")
                _add_property(entry, f"upm:{result.plan.manager}:reachability", "conditional")
            if package.package_id in possible_only:
                _add_property(entry, f"upm:{result.plan.manager}:ambiguous-reachability", "true")
                _add_property(entry, f"upm:{result.plan.manager}:reachability", "possible")
            _add_occurrence(entry, occurrence)

        for edge in result.edges:
            source = refs.get(edge.source_id)
            if not source:
                continue
            if edge.ambiguous:
                ambiguous_omitted[source] += 1
                continue
            if edge.target_id is None:
                unresolved_omitted[source] += 1
                continue
            target_package = package_by_id.get(edge.target_id)
            target = refs.get(edge.target_id)
            if target is None:
                if target_package is not None and _registry_purl(target_package) is None:
                    non_registry_omitted[source] += 1
                else:
                    unresolved_omitted[source] += 1
                continue
            if edge.source_id in possible_only:
                ambiguous_omitted[source] += 1
                continue
            if _edge_is_conditional(edge):
                conditional_omitted[source] += 1
                continue
            if source != target:
                dependency_sets.setdefault(source, set()).add(target)

        for ref, count in conditional_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:conditional-edges-omitted", str(count))
        for ref, count in ambiguous_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:ambiguous-edges-omitted", str(count))
        for ref, count in unresolved_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:unresolved-edges-omitted", str(count))
        for ref, count in non_registry_omitted.items():
            _add_property(components[ref], f"upm:{result.plan.manager}:non-registry-edges-omitted", str(count))

    valid_refs = set(components)
    cleaned_dependencies: dict[str, set[str]] = {}
    for ref, values in dependency_sets.items():
        if ref not in valid_refs:
            continue
        kept = {value for value in values if value in valid_refs and value != ref}
        if kept:
            cleaned_dependencies[ref] = kept

    merged["components"] = [components[ref] for ref in sorted(components)]
    if cleaned_dependencies:
        merged["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(values)}
            for ref, values in sorted(cleaned_dependencies.items())
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


def _package_purl(package: dict[str, Any]) -> str | None:
    for ref in package.get("externalRefs", []):
        if not isinstance(ref, dict):
            continue
        if ref.get("referenceType") == "purl" and isinstance(ref.get("referenceLocator"), str):
            return ref["referenceLocator"]
    return None


def merge_python_lock_spdx(base: dict[str, Any], results: list[PythonLockGraphResult]) -> dict[str, Any]:
    merged = copy.deepcopy(base)

    # SPDX 2.3 static package records do not retain per-component occurrence
    # provenance. Remove structured-lock package PURLs before rebuilding the
    # certainty-aware subset. Public callers should additionally use
    # suppress_python_lock_static_inventory before constructing the base document
    # so an identical PURL observed by another component is never lost here.
    provider_purls = _result_registry_purls(results)
    removed_ids: set[str] = set()
    retained_packages: list[dict[str, Any]] = []
    for package in merged.get("packages", []):
        if not isinstance(package, dict) or not isinstance(package.get("SPDXID"), str):
            continue
        if _package_purl(package) in provider_purls:
            removed_ids.add(package["SPDXID"])
        else:
            retained_packages.append(package)
    merged["packages"] = retained_packages

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
            if source not in removed_ids and target not in removed_ids:
                relationships.add((source, kind, target))

    for result in results:
        if not result.succeeded:
            continue
        allowed, _conditional_only, possible_only = _python_lock_reachability_states(result)
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
            if edge.ambiguous or edge.target_id is None or _edge_is_conditional(edge):
                continue
            if edge.source_id in possible_only:
                continue
            source = refs.get(edge.source_id)
            target = refs.get(edge.target_id)
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
