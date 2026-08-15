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
    identities: tuple[str, ...]
    purls: tuple[str, ...]
    packages: tuple[tuple[str, str], ...]
    projects: int
    components: int
    bytes: int | None
    files: int | None
    uses: tuple[CargoCacheUse, ...]

    @property
    def identity(self) -> str | None:
        return self.identities[0] if len(self.identities) == 1 else None

    @property
    def purl(self) -> str | None:
        return self.purls[0] if len(self.purls) == 1 and len(self.identities) == 1 else None

    @property
    def name(self) -> str | None:
        return self.packages[0][0] if len(self.packages) == 1 else None

    @property
    def version(self) -> str | None:
        return self.packages[0][1] if len(self.packages) == 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'cache_kind': self.cache_kind,
            'identity': self.identity,
            'identities': list(self.identities),
            'purl': self.purl,
            'purls': list(self.purls),
            'name': self.name,
            'version': self.version,
            'packages': [
                {'name': name, 'version': version}
                for name, version in self.packages
            ],
            'projects': self.projects,
            'components': self.components,
            'bytes': self.bytes,
            'files': self.files,
            'shared_across_projects': self.projects > 1,
            'cache_backed': True,
            'reclaimable': False,
            'uses': [use.to_dict() for use in self.uses],
        }


def _source_object_root(
    crate_dir: Path,
    registry_source_root: Path,
    git_checkout_root: Path,
) -> tuple[str, Path] | None:
    """Return the physical Cargo source object containing a package manifest.

    Cargo registry source objects have the shape
    ``registry/src/<index>/<crate-version>/...``. Git worktrees have the shape
    ``git/checkouts/<repo>/<revision>/...``. Attribution is performed at those
    object roots so nested workspace crates do not recursively claim overlapping
    byte ranges as independent physical cache objects.
    """

    for kind, boundary in (
        ('registry-source', registry_source_root),
        ('git-checkout', git_checkout_root),
    ):
        try:
            relative = crate_dir.relative_to(boundary)
        except ValueError:
            continue
        if len(relative.parts) < 2:
            return None
        object_root = (boundary / relative.parts[0] / relative.parts[1]).resolve()
        try:
            object_root.relative_to(boundary)
        except ValueError:
            return None
        if not object_root.is_dir() or object_root.is_symlink():
            return None
        return kind, object_root
    return None


def cargo_cache_uses(
    project: str | Path,
    cargo_results: Iterable[object],
    cargo_home: str | Path,
) -> tuple[list[CargoCacheUse], list[dict[str, str]]]:
    project_root = Path(project).expanduser().resolve()
    home = Path(cargo_home).expanduser().resolve()
    registry_source_root = (home / 'registry' / 'src').resolve()
    git_checkout_root = (home / 'git' / 'checkouts').resolve()
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
            source_object = _source_object_root(crate_dir, registry_source_root, git_checkout_root)
            if source_object is None:
                skipped.append({
                    'component': component,
                    'package': name,
                    'version': version,
                    'reason': (
                        'package source is not inside a canonical CARGO_HOME '
                        'registry/src/<index>/<object> or git/checkouts/<repo>/<revision> object'
                    ),
                })
                continue
            cache_kind, physical_root = source_object
            purl = None
            if isinstance(source, str) and source.startswith('registry+'):
                purl = purl_for('rust', name, version)
            uses.append(CargoCacheUse(
                project=str(project_root),
                component=component,
                package_id=package_id,
                name=name,
                version=version,
                purl=purl,
                source=source if isinstance(source, str) else None,
                cache_kind=cache_kind,
                path=str(physical_root),
            ))

    return sorted(uses, key=lambda item: (item.path, item.project, item.component, item.package_id)), skipped


def aggregate_cargo_cache_uses(
    uses: Iterable[CargoCacheUse],
    *,
    measure: bool = False,
) -> list[CargoCacheGroup]:
    grouped: dict[tuple[str, str], list[CargoCacheUse]] = {}
    for use in uses:
        grouped.setdefault((use.path, use.cache_kind), []).append(use)

    groups: list[CargoCacheGroup] = []
    seen: set[tuple[int, int]] = set()
    for (path_text, cache_kind), occurrences in sorted(grouped.items()):
        path = Path(path_text)
        size = files = None
        if measure and path.is_dir() and not path.is_symlink():
            size, files = directory_size(path, seen=seen)
        identities = tuple(sorted({use.purl or use.package_id for use in occurrences}))
        purls = tuple(sorted({use.purl for use in occurrences if use.purl}))
        packages = tuple(sorted({(use.name, use.version) for use in occurrences}))
        groups.append(CargoCacheGroup(
            path=path_text,
            cache_kind=cache_kind,
            identities=identities,
            purls=purls,
            packages=packages,
            projects=len({item.project for item in occurrences}),
            components=len({(item.project, item.component) for item in occurrences}),
            bytes=size,
            files=files,
            uses=tuple(sorted(occurrences, key=lambda item: (item.project, item.component, item.package_id))),
        ))
    return groups
