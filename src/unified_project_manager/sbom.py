from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .models import Component, ProjectGraph, ResolvedPackage

CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_SPEC_VERSION = "1.7"


def _encode(value: str) -> str:
    return quote(value, safe=".-_~")


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
        return f"pkg:golang/{_encode(name)}@{_encode(version)}"
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
        return purl_for("go", package.name, package.version)
    return None


def _fallback_ref(component_key: str, component: Component, package: ResolvedPackage) -> str:
    identity = "\0".join((component_key, component.ecosystem, package.name, package.version, package.source or "", package.location or ""))
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
