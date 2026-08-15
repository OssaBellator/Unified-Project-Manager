from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .sbom import purl_for
from .storage import directory_size


@dataclass(frozen=True)
class GoCacheUse:
    project: str
    component: str
    module: str
    version: str
    purl: str
    path: str
    replacement: bool
    cache_kind: str = 'module-source'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoCacheGroup:
    path: str
    purl: str
    module: str
    version: str
    projects: int
    components: int
    bytes: int | None
    files: int | None
    uses: tuple[GoCacheUse, ...]
    cache_kind: str = 'module-source'

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'cache_kind': self.cache_kind,
            'purl': self.purl,
            'module': self.module,
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


def _module_directory(module: object) -> str | None:
    replacement_name = getattr(module, 'replacement_name', None)
    replacement_version = getattr(module, 'replacement_version', None)
    replacement_dir = getattr(module, 'replacement_dir', None)
    if replacement_name is not None and isinstance(replacement_version, str) and replacement_version:
        if isinstance(replacement_dir, str) and replacement_dir:
            return replacement_dir
    for field in ('directory', 'dir'):
        value = getattr(module, field, None)
        if isinstance(value, str) and value:
            return value
    return None


def _download_artifact_paths(
    directory: Path,
    cache_root: Path,
) -> list[tuple[str, Path]]:
    """Map a native-reported module directory to existing download artifacts.

    This deliberately does not encode a logical Go module path or version.
    Instead it reuses the already-escaped relative path present in the exact
    module directory reported by Go. If that physical directory does not have
    the canonical ``name@version`` shape, no download-cache attribution is
    attempted.
    """

    try:
        relative = directory.relative_to(cache_root)
    except ValueError:
        return []
    if not relative.parts or relative.parts[0] == 'cache':
        return []

    encoded_name, separator, encoded_version = relative.name.rpartition('@')
    if not separator or not encoded_name or not encoded_version:
        return []

    download_root = (cache_root / 'cache' / 'download').resolve()
    artifact_root = download_root / relative.parent / encoded_name / '@v'
    result: list[tuple[str, Path]] = []
    for suffix in ('info', 'mod', 'zip', 'ziphash'):
        candidate = artifact_root / f'{encoded_version}.{suffix}'
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            resolved.relative_to(download_root)
        except (OSError, ValueError):
            continue
        result.append((f'download-{suffix}', resolved))
    return result


def go_cache_uses(
    project: str | Path,
    native_results: Iterable[object],
    modcache: str | Path,
) -> tuple[list[GoCacheUse], list[dict[str, str]]]:
    project_path = Path(project).expanduser().resolve()
    cache_root = Path(modcache).expanduser().resolve()
    uses: list[GoCacheUse] = []
    skipped: list[dict[str, str]] = []
    for result in native_results:
        if not getattr(result, 'succeeded', False):
            continue
        plan = getattr(result, 'plan', None)
        component = getattr(plan, 'component', None)
        if not isinstance(component, str):
            continue
        for module in getattr(result, 'modules', []):
            if getattr(module, 'main', False):
                continue
            name = getattr(module, 'effective_name', None)
            version = getattr(module, 'effective_version', None)
            if not isinstance(name, str) or not isinstance(version, str) or not version:
                continue
            raw_directory = _module_directory(module)
            if raw_directory is None:
                skipped.append({'component': component, 'module': name, 'version': version, 'reason': 'native graph did not expose a module directory'})
                continue
            directory = Path(raw_directory).expanduser().resolve()
            try:
                directory.relative_to(cache_root)
            except ValueError:
                skipped.append({'component': component, 'module': name, 'version': version, 'reason': 'selected module directory is outside GOMODCACHE'})
                continue

            replacement = getattr(module, 'replacement_name', None) is not None
            purl = purl_for('go', name, version)
            uses.append(GoCacheUse(
                project=str(project_path),
                component=component,
                module=name,
                version=version,
                purl=purl,
                path=str(directory),
                replacement=replacement,
                cache_kind='module-source',
            ))
            for cache_kind, artifact in _download_artifact_paths(directory, cache_root):
                uses.append(GoCacheUse(
                    project=str(project_path),
                    component=component,
                    module=name,
                    version=version,
                    purl=purl,
                    path=str(artifact),
                    replacement=replacement,
                    cache_kind=cache_kind,
                ))
    return sorted(uses, key=lambda item: (item.path, item.cache_kind, item.project, item.component)), skipped


def _measure_cache_path(path: Path, seen: set[tuple[int, int]]) -> tuple[int | None, int | None]:
    if path.is_symlink():
        return None, None
    if path.is_dir():
        return directory_size(path, seen=seen)
    if not path.is_file():
        return None, None
    try:
        stat = path.stat()
    except OSError:
        return None, None
    identity = (stat.st_dev, stat.st_ino)
    if stat.st_ino and identity in seen:
        return 0, 0
    if stat.st_ino:
        seen.add(identity)
    return stat.st_size, 1


def aggregate_go_cache_uses(
    uses: Iterable[GoCacheUse],
    *,
    measure: bool = False,
) -> list[GoCacheGroup]:
    grouped: dict[tuple[str, str, str], list[GoCacheUse]] = {}
    for use in uses:
        grouped.setdefault((use.path, use.purl, use.cache_kind), []).append(use)
    result: list[GoCacheGroup] = []
    seen: set[tuple[int, int]] = set()
    for (path_text, purl, cache_kind), occurrences in sorted(grouped.items()):
        path = Path(path_text)
        size = files = None
        if measure:
            size, files = _measure_cache_path(path, seen)
        first = occurrences[0]
        result.append(GoCacheGroup(
            path=path_text,
            purl=purl,
            module=first.module,
            version=first.version,
            projects=len({item.project for item in occurrences}),
            components=len({(item.project, item.component) for item in occurrences}),
            bytes=size,
            files=files,
            uses=tuple(sorted(occurrences, key=lambda item: (item.project, item.component))),
            cache_kind=cache_kind,
        ))
    return result
