from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SbomConsistency:
    cyclonedx_purls: tuple[str, ...]
    spdx_purls: tuple[str, ...]
    only_cyclonedx: tuple[str, ...]
    only_spdx: tuple[str, ...]
    cyclonedx_relationships: tuple[tuple[str, str], ...]
    spdx_relationships: tuple[tuple[str, str], ...]
    relationship_only_cyclonedx: tuple[tuple[str, str], ...]
    relationship_only_spdx: tuple[tuple[str, str], ...]

    @property
    def consistent(self) -> bool:
        return not (
            self.only_cyclonedx
            or self.only_spdx
            or self.relationship_only_cyclonedx
            or self.relationship_only_spdx
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['consistent'] = self.consistent
        return data


def _cyclonedx_purls(document: dict[str, Any]) -> set[str]:
    return {
        component['purl']
        for component in document.get('components', [])
        if isinstance(component, dict) and isinstance(component.get('purl'), str)
    }


def _spdx_purls(document: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    purls: set[str] = set()
    by_id: dict[str, str] = {}
    for package in document.get('packages', []):
        if not isinstance(package, dict) or not isinstance(package.get('SPDXID'), str):
            continue
        for ref in package.get('externalRefs', []) if isinstance(package.get('externalRefs'), list) else []:
            if not isinstance(ref, dict):
                continue
            if ref.get('referenceType') == 'purl' and isinstance(ref.get('referenceLocator'), str):
                purl = ref['referenceLocator']
                purls.add(purl)
                by_id[package['SPDXID']] = purl
                break
    return purls, by_id


def _cyclonedx_relationships(document: dict[str, Any], purls: set[str]) -> set[tuple[str, str]]:
    relationships: set[tuple[str, str]] = set()
    for dependency in document.get('dependencies', []) if isinstance(document.get('dependencies'), list) else []:
        if not isinstance(dependency, dict) or not isinstance(dependency.get('ref'), str):
            continue
        source = dependency['ref']
        if source not in purls:
            continue
        for target in dependency.get('dependsOn', []) if isinstance(dependency.get('dependsOn'), list) else []:
            if isinstance(target, str) and target in purls and target != source:
                relationships.add((source, target))
    return relationships


def _spdx_relationships(document: dict[str, Any], by_id: dict[str, str]) -> set[tuple[str, str]]:
    relationships: set[tuple[str, str]] = set()
    for relationship in document.get('relationships', []) if isinstance(document.get('relationships'), list) else []:
        if not isinstance(relationship, dict) or relationship.get('relationshipType') != 'DEPENDS_ON':
            continue
        source = by_id.get(relationship.get('spdxElementId'))
        target = by_id.get(relationship.get('relatedSpdxElement'))
        if source and target and source != target:
            relationships.add((source, target))
    return relationships


def compare_sboms(cyclonedx: dict[str, Any], spdx: dict[str, Any]) -> SbomConsistency:
    cdx_purls = _cyclonedx_purls(cyclonedx)
    spdx_purls, spdx_by_id = _spdx_purls(spdx)
    cdx_relationships = _cyclonedx_relationships(cyclonedx, cdx_purls)
    spdx_relationships = _spdx_relationships(spdx, spdx_by_id)
    return SbomConsistency(
        cyclonedx_purls=tuple(sorted(cdx_purls)),
        spdx_purls=tuple(sorted(spdx_purls)),
        only_cyclonedx=tuple(sorted(cdx_purls - spdx_purls)),
        only_spdx=tuple(sorted(spdx_purls - cdx_purls)),
        cyclonedx_relationships=tuple(sorted(cdx_relationships)),
        spdx_relationships=tuple(sorted(spdx_relationships)),
        relationship_only_cyclonedx=tuple(sorted(cdx_relationships - spdx_relationships)),
        relationship_only_spdx=tuple(sorted(spdx_relationships - cdx_relationships)),
    )
