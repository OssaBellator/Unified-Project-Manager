from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from .models import ProjectGraph
from .query import normalize_package_name

ChangeStatus = Literal['added', 'removed', 'changed']


@dataclass(frozen=True)
class DirectDependencyChange:
    component: str
    ecosystem: str
    name: str
    scope: str
    status: ChangeStatus
    before_requirement: str | None
    after_requirement: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedPackageChange:
    component: str
    ecosystem: str
    name: str
    version: str
    source: str | None
    location: str | None
    status: Literal['added', 'removed']

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DependencyDelta:
    direct: tuple[DirectDependencyChange, ...]
    resolved: tuple[ResolvedPackageChange, ...]

    @property
    def changed(self) -> bool:
        return bool(self.direct or self.resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            'changed': self.changed,
            'summary': {
                'direct_changes': len(self.direct),
                'resolved_changes': len(self.resolved),
                'direct_added': sum(1 for item in self.direct if item.status == 'added'),
                'direct_removed': sum(1 for item in self.direct if item.status == 'removed'),
                'direct_requirement_changed': sum(1 for item in self.direct if item.status == 'changed'),
                'resolved_added': sum(1 for item in self.resolved if item.status == 'added'),
                'resolved_removed': sum(1 for item in self.resolved if item.status == 'removed'),
            },
            'direct': [item.to_dict() for item in self.direct],
            'resolved': [item.to_dict() for item in self.resolved],
        }


def _direct_map(graph: ProjectGraph) -> dict[tuple[str, str, str, str], tuple[str, str | None]]:
    result: dict[tuple[str, str, str, str], tuple[str, str | None]] = {}
    for component in graph.components:
        component_key = component.key(graph.root)
        for dependency in component.dependencies:
            normalized = normalize_package_name(component.ecosystem, dependency.name)
            key = (component_key, component.ecosystem, normalized, dependency.scope)
            # Multiple declarations in one normalized key are already a doctor
            # finding. Keep a deterministic representative here rather than
            # inventing merge semantics.
            candidate = (dependency.name, dependency.requirement)
            current = result.get(key)
            if current is None or repr(candidate) < repr(current):
                result[key] = candidate
    return result


def _resolved_set(graph: ProjectGraph) -> set[tuple[str, str, str, str, str | None, str | None]]:
    result: set[tuple[str, str, str, str, str | None, str | None]] = set()
    for component in graph.components:
        component_key = component.key(graph.root)
        for package in component.resolved_packages:
            normalized = normalize_package_name(component.ecosystem, package.name)
            result.add((
                component_key,
                component.ecosystem,
                normalized,
                package.version,
                package.source,
                package.location,
            ))
    return result


def dependency_delta(before: ProjectGraph, after: ProjectGraph) -> DependencyDelta:
    if before.root.resolve() != after.root.resolve():
        raise ValueError('Dependency delta requires before/after graphs for the same project root.')

    before_direct = _direct_map(before)
    after_direct = _direct_map(after)
    direct_changes: list[DirectDependencyChange] = []
    for key in sorted(set(before_direct) | set(after_direct)):
        component, ecosystem, normalized, scope = key
        old = before_direct.get(key)
        new = after_direct.get(key)
        if old == new:
            continue
        if old is None:
            status: ChangeStatus = 'added'
        elif new is None:
            status = 'removed'
        else:
            status = 'changed'
        display_name = (new or old or (normalized, None))[0]
        direct_changes.append(DirectDependencyChange(
            component=component,
            ecosystem=ecosystem,
            name=display_name,
            scope=scope,
            status=status,
            before_requirement=old[1] if old else None,
            after_requirement=new[1] if new else None,
        ))

    before_resolved = _resolved_set(before)
    after_resolved = _resolved_set(after)
    resolved_changes: list[ResolvedPackageChange] = []
    for item in sorted(before_resolved - after_resolved, key=repr):
        component, ecosystem, name, version, source, location = item
        resolved_changes.append(ResolvedPackageChange(component, ecosystem, name, version, source, location, 'removed'))
    for item in sorted(after_resolved - before_resolved, key=repr):
        component, ecosystem, name, version, source, location = item
        resolved_changes.append(ResolvedPackageChange(component, ecosystem, name, version, source, location, 'added'))

    return DependencyDelta(tuple(direct_changes), tuple(resolved_changes))
