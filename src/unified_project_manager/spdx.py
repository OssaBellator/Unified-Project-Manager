from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import Component, ProjectGraph, ResolvedPackage
from .sbom import purl_for
from .sbom_project_components import add_spdx_project_anchors
from .uv_scope import uv_scope_package_ids

SPDX_VERSION = "SPDX-2.3"
SPDX_DATA_LICENSE = "CC0-1.0"


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
    return None


def _spdx_ref(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"SPDXRef-Package-{digest}"


def _package_record(name: str, version: str | None, identity: str, purl: str | None) -> dict[str, Any]:
    package: dict[str, Any] = {
        "SPDXID": _spdx_ref(identity),
        "name": name,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": "LIBRARY",
    }
    if version:
        package["versionInfo"] = version
    if purl:
        package["externalRefs"] = [{
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": purl,
        }]
    return package


def _static_packages(graph: ProjectGraph) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, str], str]]:
    packages: dict[str, dict[str, Any]] = {}
    lookup: dict[tuple[str, str, str], str] = {}
    for component in graph.components:
        key = component.key(graph.root)
        for package in component.resolved_packages:
            purl = _registry_purl(component, package)
            identity = purl or "\0".join((key, component.ecosystem, package.name, package.version, package.source or "", package.location or ""))
            spdx_id = _spdx_ref(identity)
            packages.setdefault(spdx_id, _package_record(package.name, package.version, identity, purl))
            lookup[(component.ecosystem, package.name.lower(), package.version)] = spdx_id
    return packages, lookup


def _add_relationship(relationships: set[tuple[str, str, str]], source: str, kind: str, target: str) -> None:
    if source != target:
        relationships.add((source, kind, target))


def spdx_document(
    graph: ProjectGraph,
    *,
    go_results: list[object] | None = None,
    npm_results: list[object] | None = None,
    cargo_results: list[object] | None = None,
    uv_results: list[object] | None = None,
    created: datetime | None = None,
) -> dict[str, Any]:
    packages, lookup = _static_packages(graph)
    relationships: set[tuple[str, str, str]] = set()

    # Go selected modules may add authoritative concrete identities.
    go_logical: dict[tuple[str, str], str] = {}
    for result in go_results or []:
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
                purl = purl_for("go", effective_name, effective_version)
                identity = purl
                name = effective_name
                version = effective_version
            else:
                replacement_dir = getattr(module, "replacement_dir", None)
                identity = "\0".join((component_key, logical_name, effective_name, str(replacement_dir or "")))
                purl = None
                name = logical_name
                version = None
            spdx_id = _spdx_ref(identity)
            packages.setdefault(spdx_id, _package_record(name, version, identity, purl))
            go_logical[(component_key, logical_name)] = spdx_id
        for edge in getattr(result, "edges", []):
            if not getattr(edge, "source_selected", False):
                continue
            source = go_logical.get((component_key, getattr(edge, "source_name", "")))
            target = go_logical.get((component_key, getattr(edge, "target_name", "")))
            if source and target:
                _add_relationship(relationships, source, "DEPENDS_ON", target)

    # npm logical edges are admitted only when static package-lock provenance
    # already established the package identities.
    for result in npm_results or []:
        if not getattr(result, "succeeded", False):
            continue
        refs: dict[str, str] = {}
        for package in getattr(result, "packages", []):
            name = getattr(package, "name", None)
            version = getattr(package, "version", None)
            ref = getattr(package, "ref", None)
            if isinstance(name, str) and isinstance(version, str) and isinstance(ref, str):
                target = lookup.get(("node", name.lower(), version))
                if target:
                    refs[ref] = target
        for edge in getattr(result, "edges", []):
            source = refs.get(getattr(edge, "source_ref", ""))
            target = refs.get(getattr(edge, "target_ref", ""))
            if source and target:
                _add_relationship(relationships, source, "DEPENDS_ON", target)

    for result in cargo_results or []:
        if not getattr(result, "succeeded", False):
            continue
        refs: dict[str, str] = {}
        for package in getattr(result, "packages", []):
            package_id = getattr(package, "package_id", None)
            name = getattr(package, "name", None)
            version = getattr(package, "version", None)
            source = getattr(package, "source", None)
            if not all(isinstance(value, str) for value in (package_id, name, version)):
                continue
            if not isinstance(source, str) or not source.startswith("registry+"):
                continue
            target = lookup.get(("rust", name.lower(), version))
            if target:
                refs[package_id] = target
        for edge in getattr(result, "edges", []):
            source = refs.get(getattr(edge, "source_id", ""))
            target = refs.get(getattr(edge, "target_id", ""))
            if source and target:
                _add_relationship(relationships, source, "DEPENDS_ON", target)

    # uv.lock is authoritative package identity for registry packages. For a
    # selected workspace member, only registry packages reachable from that
    # member's locked project node are admitted; siblings remain out of scope.
    for result in uv_results or []:
        if not getattr(result, "succeeded", False):
            continue
        allowed = uv_scope_package_ids(result)
        refs: dict[str, str] = {}
        for package in getattr(result, "packages", []):
            package_id = getattr(package, "package_id", None)
            name = getattr(package, "name", None)
            version = getattr(package, "version", None)
            source_kind = getattr(package, "source_kind", None)
            if not all(isinstance(value, str) and value for value in (package_id, name, version)):
                continue
            if package_id not in allowed or source_kind != "registry":
                continue
            purl = purl_for("python", name, version)
            spdx_id = _spdx_ref(purl)
            packages.setdefault(spdx_id, _package_record(name, version, purl, purl))
            refs[package_id] = spdx_id
            normalized = re.sub(r"[-_.]+", "-", name).lower()
            lookup[("python", normalized, version)] = spdx_id
            lookup[("python", name.lower(), version)] = spdx_id

        for edge in getattr(result, "edges", []):
            source_id = getattr(edge, "source_id", "")
            target_id = getattr(edge, "target_id", "")
            if source_id not in allowed or target_id not in allowed:
                continue
            if getattr(edge, "ambiguous", False) or getattr(edge, "marker", None):
                continue
            source = refs.get(source_id)
            target = refs.get(target_id)
            if source and target:
                _add_relationship(relationships, source, "DEPENDS_ON", target)

    for spdx_id in packages:
        relationships.add(("SPDXRef-DOCUMENT", "DESCRIBES", spdx_id))

    package_list = [packages[spdx_id] for spdx_id in sorted(packages)]
    relationship_list = [
        {"spdxElementId": source, "relationshipType": kind, "relatedSpdxElement": target}
        for source, kind, target in sorted(relationships)
    ]
    identity_payload = {
        "packages": package_list,
        "relationships": relationship_list,
        "root": str(graph.root),
    }
    digest = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    timestamp = created or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    created_text = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": SPDX_DATA_LICENSE,
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"UPM SBOM for {graph.root.name or 'project'}",
        "documentNamespace": f"https://spdx.org/spdxdocs/upm-{digest}",
        "creationInfo": {
            "created": created_text,
            "creators": ["Tool: Unified Project Manager"],
        },
        "packages": package_list,
        "relationships": relationship_list,
    }
    return add_spdx_project_anchors(document, graph)


def write_spdx(document: dict[str, Any], output: str | Path) -> Path:
    target = Path(output).expanduser()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
