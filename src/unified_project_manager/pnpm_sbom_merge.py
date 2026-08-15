from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .pnpm_sbom import PnpmSbomError, stable_native_ref


def _cyclonedx_ref(component: dict[str, Any], owner: str, index: int) -> str | None:
    purl = component.get("purl")
    if isinstance(purl, str) and purl:
        return purl
    native_ref = component.get("bom-ref")
    name = component.get("name")
    if not isinstance(name, str) or not name:
        return None
    return stable_native_ref(
        owner,
        index,
        native_ref if isinstance(native_ref, str) else "",
        name,
        component.get("version") if isinstance(component.get("version"), str) else None,
    )


def _merge_properties(target: dict[str, Any], source: dict[str, Any], extras: list[dict[str, str]]) -> None:
    existing = target.setdefault("properties", [])
    if not isinstance(existing, list):
        existing = []
        target["properties"] = existing
    values = source.get("properties")
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and item not in existing:
                existing.append(copy.deepcopy(item))
    for item in extras:
        if item not in existing:
            existing.append(item)
    existing.sort(key=lambda item: (str(item.get("name", "")), str(item.get("value", ""))))


def merge_pnpm_cyclonedx(base: dict[str, Any], results: list[object]) -> dict[str, Any]:
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
            value for value in item.get("dependsOn", []) if isinstance(value, str)
        )

    for result in results:
        if not getattr(result, "succeeded", False):
            continue
        plan = getattr(result, "plan", None)
        owner = getattr(plan, "component", None)
        if not isinstance(owner, str):
            continue
        for index, document in enumerate(getattr(result, "documents", []), start=1):
            if not isinstance(document, dict) or document.get("bomFormat") != "CycloneDX":
                raise PnpmSbomError("pnpm CycloneDX provider returned a non-CycloneDX document.")
            native_components: list[tuple[dict[str, Any], bool]] = []
            metadata = document.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("component"), dict):
                native_components.append((metadata["component"], True))
            for item in document.get("components", []):
                if isinstance(item, dict):
                    native_components.append((item, False))

            ref_map: dict[str, str] = {}
            for native, project_component in native_components:
                canonical = _cyclonedx_ref(native, owner, index)
                if canonical is None:
                    continue
                native_ref = native.get("bom-ref")
                if isinstance(native_ref, str):
                    ref_map[native_ref] = canonical
                if isinstance(native.get("purl"), str):
                    ref_map[native["purl"]] = canonical

                candidate = copy.deepcopy(native)
                candidate["bom-ref"] = canonical
                target = components.get(canonical)
                if target is None:
                    target = candidate
                    components[canonical] = target
                else:
                    for key, value in candidate.items():
                        if key in {"bom-ref", "properties"}:
                            continue
                        target.setdefault(key, value)
                extras = [{"name": "upm:pnpm:identity-kind", "value": "native-lockfile-sbom"}]
                if project_component:
                    extras.append({"name": "upm:pnpm:project-component", "value": "true"})
                _merge_properties(target, candidate, extras)

            for dependency in document.get("dependencies", []):
                if not isinstance(dependency, dict):
                    continue
                native_source = dependency.get("ref")
                if not isinstance(native_source, str):
                    continue
                source = ref_map.get(native_source)
                if source is None:
                    continue
                for native_target in dependency.get("dependsOn", []):
                    if not isinstance(native_target, str):
                        continue
                    target = ref_map.get(native_target)
                    if target and target != source:
                        dependencies.setdefault(source, set()).add(target)

    merged["components"] = [components[ref] for ref in sorted(components)]
    if dependencies:
        merged["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(values)}
            for ref, values in sorted(dependencies.items())
            if values
        ]
    else:
        merged.pop("dependencies", None)
    return merged


def _native_spdx_purl(package: dict[str, Any]) -> str | None:
    refs = package.get("externalRefs")
    if not isinstance(refs, list):
        return None
    for item in refs:
        if not isinstance(item, dict):
            continue
        if item.get("referenceType") == "purl" and isinstance(item.get("referenceLocator"), str):
            return item["referenceLocator"]
    return None


def _spdx_id(identity: str) -> str:
    return f"SPDXRef-Package-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def merge_pnpm_spdx(base: dict[str, Any], results: list[object]) -> dict[str, Any]:
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
        if not getattr(result, "succeeded", False):
            continue
        plan = getattr(result, "plan", None)
        owner = getattr(plan, "component", None)
        if not isinstance(owner, str):
            continue
        for index, document in enumerate(getattr(result, "documents", []), start=1):
            if not isinstance(document, dict) or document.get("spdxVersion") != "SPDX-2.3":
                raise PnpmSbomError("pnpm SPDX provider returned a non-SPDX-2.3 document.")
            ref_map: dict[str, str] = {}
            for native in document.get("packages", []):
                if not isinstance(native, dict):
                    continue
                native_id = native.get("SPDXID")
                name = native.get("name")
                if not isinstance(native_id, str) or not isinstance(name, str) or not name:
                    continue
                purl = _native_spdx_purl(native)
                if purl:
                    identity = purl
                else:
                    identity = stable_native_ref(
                        owner,
                        index,
                        native_id,
                        name,
                        native.get("versionInfo") if isinstance(native.get("versionInfo"), str) else None,
                    )
                canonical = _spdx_id(identity)
                ref_map[native_id] = canonical
                candidate = copy.deepcopy(native)
                candidate["SPDXID"] = canonical
                packages.setdefault(canonical, candidate)

            for relation in document.get("relationships", []):
                if not isinstance(relation, dict) or relation.get("relationshipType") != "DEPENDS_ON":
                    continue
                source = ref_map.get(relation.get("spdxElementId"))
                target = ref_map.get(relation.get("relatedSpdxElement"))
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
