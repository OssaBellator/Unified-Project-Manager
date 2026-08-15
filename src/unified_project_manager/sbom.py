from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .models import Component, ProjectGraph, ResolvedPackage

CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_SPEC_VERSION = "1.7"


def _encode(value: str) -> str:
    return quote(value, safe=".-_~")


def _namespace_and_name(value: str) -> tuple[str, str]:
    segments = [segment for segment in value.split("/") if segment]
    if len(segments) < 2:
        raise ValueError(f"Package identity requires namespace/name form: {value!r}")
    namespace = "/".join(_encode(segment) for segment in segments[:-1])
    return namespace, _encode(segments[-1])


def purl_for(ecosystem: str, name: str, version: str) -> str:
    if ecosystem == "node":
        if name.startswith("@") and "/" in name:
            namespace, package = name.split("/", 1)
            return f"pkg:npm/{_encode(namespace)}/{_encode(package)}@{_encode(version)}"
        return f"pkg:npm/{_encode(name)}@{_encode(version)}"
    if ecosystem == "python":
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        return f"pkg:pypi/{_encode(normalized)}@{_encode(version)}"
    if ecosystem == "rust":
        return f"pkg:cargo/{_encode(name)}@{_encode(version)}"
    if ecosystem == "go":
        namespace, package = _namespace_and_name(name)
        return f"pkg:golang/{namespace}/{package}@{_encode(version)}"
    raise ValueError(f"No Package URL mapping is defined for ecosystem '{ecosystem}'.")


def _registry_purl(component: Component, package: ResolvedPackage) -> str | None:
    source = package.source or ""
    if component.ecosystem == "node":
        if source.startswith(("git+", "git:", "file:", "link:")):
            return None
        return purl_for("node", package.name, package.version)
    if component.ecosystem == "python":
        if source.startswith(("git:", "path:", "editable:", "virtual:", "url:")):
            return None
        return purl_for("python", package.name, package.version)
    if component.ecosystem == "rust":
        if not source.startswith("registry+"):
            return None
        return purl_for("rust", package.name, package.version)
    if component.ecosystem == "go":
        try:
            return purl_for("go", package.name, package.version)
        except ValueError:
            return None
    return None


def _fallback_ref(component_key: str, component: Component, package: ResolvedPackage) -> str:
    identity = "\0".join((
        component_key,
        component.ecosystem,
        package.name,
        package.version,
        package.source or "",
        package.location or "",
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"urn:upm:component:sha256:{digest}"


def cyclonedx_bom(graph: ProjectGraph) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {}
    occurrence_sets: dict[str, set[str]] = {}

    for component in graph.components:
        component_key = component.key(graph.root)
        for package in component.resolved_packages:
            purl = _registry_purl(component, package)
            identity = purl or _fallback_ref(component_key, component, package)
            if identity not in components:
                entry: dict[str, Any] = {
                    "type": "library",
                    "name": package.name,
                    "version": package.version,
                    "bom-ref": identity,
                }
                if purl:
                    entry["purl"] = purl
                components[identity] = entry
                occurrence_sets[identity] = set()
            if package.location:
                occurrence_sets[identity].add(f"{component_key}:{package.location}")

    for identity, locations in occurrence_sets.items():
        if locations:
            components[identity]["evidence"] = {
                "occurrences": [{"location": location} for location in sorted(locations)]
            }

    return {
        "$schema": CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "version": 1,
        "components": [components[identity] for identity in sorted(components)],
    }


def write_cyclonedx(graph: ProjectGraph, output: str | Path) -> Path:
    import json

    target = Path(output).expanduser()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cyclonedx_bom(graph), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _go_native_ref(name: str, version: str) -> str | None:
    try:
        return purl_for("go", name, version)
    except ValueError:
        return None


def _go_provenance_properties(module: object) -> list[dict[str, str]]:
    properties = [{"name": "upm:go:identity-kind", "value": "selected-module"}]
    if getattr(module, "indirect", False):
        properties.append({"name": "upm:go:indirect", "value": "true"})
    go_version = getattr(module, "effective_go_version", None)
    if isinstance(go_version, str) and go_version:
        properties.append({"name": "upm:go:go-version", "value": go_version})
    checksum = getattr(module, "effective_checksum", None)
    if isinstance(checksum, str) and checksum:
        properties.append({"name": "upm:go:sum", "value": checksum})
    go_mod_checksum = getattr(module, "effective_go_mod_checksum", None)
    if isinstance(go_mod_checksum, str) and go_mod_checksum:
        properties.append({"name": "upm:go:go-mod-sum", "value": go_mod_checksum})
    origin = getattr(module, "effective_origin", None)
    if isinstance(origin, dict) and origin:
        properties.append({
            "name": "upm:go:origin",
            "value": json.dumps(origin, sort_keys=True, separators=(",", ":")),
        })
    return properties


def _extend_unique_properties(entry: dict[str, Any], values: list[dict[str, str]]) -> None:
    properties = entry.setdefault("properties", [])
    for value in values:
        if value not in properties:
            properties.append(value)


def cyclonedx_bom_with_native(graph: ProjectGraph, native_results: list[object]) -> dict[str, Any]:
    """Enrich the normal BOM with authoritative live native inventory.

    Native results currently come from Go build-list queries. The deliberately
    loose annotation avoids coupling the static exporter to subprocess planning.
    """
    bom = cyclonedx_bom(graph)
    component_entries: dict[str, dict[str, Any]] = {
        entry["bom-ref"]: entry for entry in bom["components"]
    }
    occurrence_sets: dict[str, set[str]] = {}
    for ref, entry in component_entries.items():
        occurrence_sets[ref] = {
            occurrence["location"]
            for occurrence in entry.get("evidence", {}).get("occurrences", [])
            if isinstance(occurrence, dict) and isinstance(occurrence.get("location"), str)
        }

    logical_refs: dict[tuple[str, str], str] = {}
    dependency_sets: dict[str, set[str]] = {}

    for result in native_results:
        if not getattr(result, "succeeded", False):
            continue
        plan = getattr(result, "plan", None)
        component_key = getattr(plan, "component", None)
        if not isinstance(component_key, str):
            continue
        for module in getattr(result, "modules", []):
            if getattr(module, "main", False):
                continue
            logical_name = getattr(module, "name", None)
            effective_name = getattr(module, "effective_name", None)
            effective_version = getattr(module, "effective_version", None)
            if not isinstance(logical_name, str) or not isinstance(effective_name, str):
                continue

            if isinstance(effective_version, str) and effective_version:
                purl = _go_native_ref(effective_name, effective_version)
                if purl is not None:
                    ref = purl
                else:
                    identity = "\0".join((component_key, logical_name, effective_name, effective_version))
                    ref = f"urn:upm:go-module:sha256:{hashlib.sha256(identity.encode()).hexdigest()}"
                entry = component_entries.get(ref)
                if entry is None:
                    entry = {
                        "type": "library",
                        "name": effective_name,
                        "version": effective_version,
                        "bom-ref": ref,
                    }
                    if purl is not None:
                        entry["purl"] = purl
                    component_entries[ref] = entry
                    occurrence_sets[ref] = set()
                _extend_unique_properties(entry, _go_provenance_properties(module))
                if logical_name != effective_name:
                    _extend_unique_properties(entry, [{"name": "upm:go:logical-module", "value": logical_name}])
            else:
                replacement_name = getattr(module, "replacement_name", None)
                replacement_dir = getattr(module, "replacement_dir", None)
                identity = "\0".join((
                    component_key,
                    logical_name,
                    str(replacement_name or ""),
                    str(replacement_dir or ""),
                ))
                ref = f"urn:upm:go-local:sha256:{hashlib.sha256(identity.encode()).hexdigest()}"
                if ref not in component_entries:
                    entry = {
                        "type": "library",
                        "name": logical_name,
                        "bom-ref": ref,
                        "properties": [
                            {"name": "upm:go:replacement-kind", "value": "local"},
                            {"name": "upm:go:replacement", "value": str(replacement_name or replacement_dir or "local")},
                        ],
                    }
                    component_entries[ref] = entry
                    occurrence_sets[ref] = set()
                _extend_unique_properties(entry, _go_provenance_properties(module))
            logical_refs[(component_key, logical_name)] = ref
            occurrence_sets.setdefault(ref, set()).add(component_key)

    for result in native_results:
        if not getattr(result, "succeeded", False):
            continue
        plan = getattr(result, "plan", None)
        component_key = getattr(plan, "component", None)
        if not isinstance(component_key, str):
            continue
        for edge in getattr(result, "edges", []):
            if not getattr(edge, "source_selected", False):
                continue
            source_ref = logical_refs.get((component_key, getattr(edge, "source_name", "")))
            target_ref = logical_refs.get((component_key, getattr(edge, "target_name", "")))
            if source_ref and target_ref and source_ref != target_ref:
                dependency_sets.setdefault(source_ref, set()).add(target_ref)

    for ref, locations in occurrence_sets.items():
        if locations:
            component_entries[ref]["evidence"] = {
                "occurrences": [{"location": location} for location in sorted(locations)]
            }
        properties = component_entries[ref].get("properties")
        if isinstance(properties, list):
            properties.sort(key=lambda item: (item.get("name", ""), item.get("value", "")))

    bom["components"] = [component_entries[ref] for ref in sorted(component_entries)]
    if dependency_sets:
        bom["dependencies"] = [
            {"ref": ref, "dependsOn": sorted(dependency_sets[ref])}
            for ref in sorted(dependency_sets)
        ]
    return bom


def write_cyclonedx_with_native(
    graph: ProjectGraph,
    native_results: list[object],
    output: str | Path,
) -> Path:
    import json

    target = Path(output).expanduser()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(cyclonedx_bom_with_native(graph, native_results), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
