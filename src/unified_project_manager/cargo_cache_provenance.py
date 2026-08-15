from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .sbom import purl_for
from .storage import directory_size


@dataclass(frozen=True)
class CargoCacheUse:
    project: str
    component: str
    package_id: str
    name: str
    version: str
    purl: str | None
    source: str | None
    cache_kind: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CargoCacheGroup:
    path: str
    cache_kind: str
    identity: str
    purl: str | None
    name: str
    version: str
    projects: int
    components: int
    bytes: int | None
    files: int | None
    uses: tuple[CargoCacheUse, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'cache_kind': self.cache_kind,
            'identity': self.identity,
            'purl': self.purl,
            'name': self.name,
            'version': self.version,
            'projects': self.projects,
            'components': self.components,
            'bytes': self.bytes,
            'files': self.files,
            'shared_across_projects': self.projects > 1,
            'cache_backed': True,
            'reclaimable': False,
            'uses': [use.to_dict() for use in self.uses],
        }


def cargo_cache_uses(
    project: str | Path,
    cargo_results: Iterable[object],
    cargo_home: str | Path,
) -> tuple[list[CargoCacheUse], list[dict[str, str]]]:
    project_root = Path(project).expanduser().resolve()
    home = Path(cargo_home).expanduser().resolve()
    registry_root = home / 'registry'
    git_root = home / 'git'
    uses: list[CargoCacheUse] = []
    skipped: list[dict[str, str]] = []

    for result in cargo_results:
        if not getattr(result, 'succeeded', False):
            continue
        plan = getattr(result, 'plan', None)
        component = getattr(plan, 'component', None)
        if not isinstance(component, str):
            continue
        for package in getattr(result, 'packages', []):
            package_id = getattr(package, 'package_id', None)
            name = getattr(package, 'name', None)
            version = getattr(package, 'version', None)
            source = getattr(package, 'source', None)
            manifest_path = getattr(package, 'manifest_path', None)
            if not all(isinstance(value, str) and value for value in (package_id, name, version)):
                continue
            if not isinstance(manifest_path, str) or not manifest_path:
                skipped.append({
                    'component': component,
                    'package': name,
                    'version': version,
                    'reason': 'cargo metadata did not expose a manifest_path',
                })
                continue
            crate_dir = Path(manifest_path).expanduser().resolve().parent
            cache_kind = None
            for kind, boundary in (('registry-source', registry_root), ('git-checkout', git_root)):
                try:
                    crate_dir.relative_to(boundary.resolve())
                except ValueError:
                    continue
                cache_kind = kind
                break
            if cache_kind is None:
                # Workspace/path dependencies and external checkout locations are
                # not Cargo-home cache ownership evidence.
                skipped.append({
                    'component': component,
                    'package': name,
                    'version': version,
                    'reason': 'package source directory is outside CARGO_HOME registry/git roots',
                })
                continue
            purl = None
            if isinstance(source, str) and source.startswith('registry+'):
                purl = purl_for('rust', name, version)
            identity = purl or package_id
            uses.append(CargoCacheUse(
                project=str(project_root),
                component=component,
                package_id=package_id,
                name=name,
                version=version,
                purl=purl,
                source=source if isinstance(source, str) else None,
                cache_kind=cache_kind,
                path=str(crate_dir),
            ))

    return sorted(uses, key=lambda item: (item.path, item.project, item.component, item.package_id)), skipped


def aggregate_cargo_cache_uses(
    uses: Iterable[CargoCacheUse],
    *,
    measure: bool = False,
) -> list[CargoCacheGroup]:
    grouped: dict[tuple[str, str], list[CargoCacheUse]] = {}
    for use in uses:
        identity = use.purl or use.package_id
        grouped.setdefault((use.path, identity), []).append(use)

    groups: list[CargoCacheGroup] = []
    seen: set[tuple[int, int]] = set()
    for (path_text, identity), occurrences in sorted(grouped.items()):
        path = Path(path_text)
        size = files = None
        if measure and path.is_dir() and not path.is_symlink():
            size, files = directory_size(path, seen=seen)
        first = occurrences[0]
        groups.append(CargoCacheGroup(
            path=path_text,
            cache_kind=first.cache_kind,
            identity=identity,
            purl=first.purl,
            name=first.name,
            version=first.version,
            projects=len({item.project for item in occurrences}),
            components=len({(item.project, item.component) for item in occurrences}),
            bytes=size,
            files=files,
            uses=tuple(sorted(occurrences, key=lambda item: (item.project, item.component, item.package_id))),
        ))
    return groups
