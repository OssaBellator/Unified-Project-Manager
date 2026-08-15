from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .discovery import discover
from .models import Component, ResolvedPackage
from .registry import registered_paths
from .sbom import purl_for


@dataclass(frozen=True)
class PackageUse:
    identity: str
    purl: str | None
    ecosystem: str
    name: str
    version: str
    source: str | None
    project: str
    component: str
    manager: str | None
    location: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PackageProvenanceGroup:
    identity: str
    purl: str | None
    ecosystem: str
    name: str
    version: str
    projects: int
    components: int
    managers: tuple[str, ...]
    sources: tuple[str, ...]
    occurrences: tuple[PackageUse, ...]

    @property
    def shared_across_projects(self) -> bool:
        return self.projects > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            'identity': self.identity,
            'purl': self.purl,
            'ecosystem': self.ecosystem,
            'name': self.name,
            'version': self.version,
            'projects': self.projects,
            'components': self.components,
            'managers': list(self.managers),
            'sources': list(self.sources),
            'shared_across_projects': self.shared_across_projects,
            'physical_duplication_known': False,
            'reclaimable': False,
            'occurrences': [item.to_dict() for item in self.occurrences],
        }


def _trusted_purl(component: Component, package: ResolvedPackage) -> str | None:
    source = package.source or ''
    if component.ecosystem == 'node':
        if source.startswith(('git+', 'git:', 'file:', 'link:')):
            return None
        return purl_for('node', package.name, package.version)
    if component.ecosystem == 'python':
        if source.startswith(('git:', 'path:', 'editable:', 'virtual:', 'url:')):
            return None
        return purl_for('python', package.name, package.version)
    if component.ecosystem == 'rust':
        if not source.startswith('registry+'):
            return None
        return purl_for('rust', package.name, package.version)
    return None


def _fallback_identity(component: Component, package: ResolvedPackage) -> str:
    normalized = package.name.lower()
    if component.ecosystem == 'python':
        normalized = re.sub(r'[-_.]+', '-', normalized)
    payload = '\0'.join((component.ecosystem, normalized, package.version, package.source or ''))
    return 'urn:upm:resolved:sha256:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def project_package_uses(root: str | Path) -> list[PackageUse]:
    graph = discover(root)
    project = str(graph.root)
    uses: list[PackageUse] = []
    for component in graph.components:
        key = component.key(graph.root)
        for package in component.resolved_packages:
            purl = _trusted_purl(component, package)
            identity = purl or _fallback_identity(component, package)
            uses.append(PackageUse(
                identity=identity,
                purl=purl,
                ecosystem=component.ecosystem,
                name=package.name,
                version=package.version,
                source=package.source,
                project=project,
                component=key,
                manager=component.manager,
                location=package.location,
            ))
    return sorted(uses, key=lambda item: (
        item.ecosystem, item.name.lower(), item.version, item.project, item.component, item.location or ''
    ))


def fleet_package_uses(
    registry: str | Path | None = None,
    *,
    roots: Iterable[str | Path] | None = None,
) -> tuple[list[PackageUse], list[str]]:
    selected = [Path(value).expanduser().resolve() for value in roots] if roots is not None else registered_paths(registry)
    uses: list[PackageUse] = []
    skipped: list[str] = []
    for root in selected:
        if not root.is_dir():
            skipped.append(str(root))
            continue
        try:
            uses.extend(project_package_uses(root))
        except (OSError, ValueError):
            skipped.append(str(root))
    return sorted(uses, key=lambda item: (
        item.identity, item.project, item.component, item.location or ''
    )), sorted(skipped)


def aggregate_package_provenance(uses: Iterable[PackageUse]) -> list[PackageProvenanceGroup]:
    grouped: dict[str, list[PackageUse]] = {}
    for use in uses:
        grouped.setdefault(use.identity, []).append(use)
    result: list[PackageProvenanceGroup] = []
    for identity, occurrences in sorted(grouped.items()):
        first = occurrences[0]
        result.append(PackageProvenanceGroup(
            identity=identity,
            purl=first.purl,
            ecosystem=first.ecosystem,
            name=first.name,
            version=first.version,
            projects=len({item.project for item in occurrences}),
            components=len({(item.project, item.component) for item in occurrences}),
            managers=tuple(sorted({item.manager for item in occurrences if item.manager})),
            sources=tuple(sorted({item.source for item in occurrences if item.source})),
            occurrences=tuple(sorted(occurrences, key=lambda item: (item.project, item.component, item.location or ''))),
        ))
    return result


def version_divergence(groups: Iterable[PackageProvenanceGroup]) -> list[dict[str, Any]]:
    by_name: dict[tuple[str, str], list[PackageProvenanceGroup]] = {}
    for group in groups:
        name = group.name.lower()
        if group.ecosystem == 'python':
            name = re.sub(r'[-_.]+', '-', name)
        by_name.setdefault((group.ecosystem, name), []).append(group)
    result = []
    for (ecosystem, name), items in sorted(by_name.items()):
        versions = sorted({item.version for item in items})
        projects = sorted({use.project for item in items for use in item.occurrences})
        if len(versions) < 2 or len(projects) < 2:
            continue
        result.append({
            'ecosystem': ecosystem,
            'name': name,
            'versions': versions,
            'projects': projects,
            'physical_duplication_known': False,
            'reclaimable': False,
        })
    return result
