from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from .models import ProjectGraph


@dataclass(frozen=True)
class PackageOccurrence:
    component: str
    version: str
    source: str | None
    location: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DuplicateObservation:
    category: str
    ecosystem: str
    name: str
    versions: tuple[str, ...]
    sources: tuple[str, ...]
    components: tuple[str, ...]
    occurrences: tuple[PackageOccurrence, ...]
    reclaimable: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "ecosystem": self.ecosystem,
            "name": self.name,
            "versions": list(self.versions),
            "sources": list(self.sources),
            "components": list(self.components),
            "occurrences": [item.to_dict() for item in self.occurrences],
            "reclaimable": self.reclaimable,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class DuplicateReport:
    observations: tuple[DuplicateObservation, ...]
    components_with_resolved_inventory: int
    total_components: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [item.to_dict() for item in self.observations],
            "coverage": {
                "components_with_resolved_inventory": self.components_with_resolved_inventory,
                "total_components": self.total_components,
            },
            "reclaimable": False,
            "physical_duplicate_bytes_analyzed": False,
        }


def _occurrence_sort_key(item: PackageOccurrence) -> tuple[str, str, str, str]:
    return (item.component, item.version, item.source or "", item.location or "")


def classify_duplicates(graph: ProjectGraph) -> DuplicateReport:
    by_name: dict[tuple[str, str], list[PackageOccurrence]] = defaultdict(list)
    coverage = 0
    for component in graph.components:
        if component.resolved_packages:
            coverage += 1
        key = component.key(graph.root)
        for package in component.resolved_packages:
            by_name[(component.ecosystem, package.name)].append(PackageOccurrence(
                component=key,
                version=package.version,
                source=package.source,
                location=package.location,
            ))

    observations: list[DuplicateObservation] = []
    for (ecosystem, name), values in sorted(by_name.items()):
        occurrences = tuple(sorted(values, key=_occurrence_sort_key))
        versions = tuple(sorted({item.version for item in occurrences}))
        sources = tuple(sorted({item.source for item in occurrences if item.source}))
        components = tuple(sorted({item.component for item in occurrences}))

        exact_groups: dict[tuple[str, str | None], list[PackageOccurrence]] = defaultdict(list)
        for item in occurrences:
            exact_groups[(item.version, item.source)].append(item)
        repeated = [
            member
            for _identity, members in sorted(exact_groups.items(), key=lambda item: (item[0][0], item[0][1] or ""))
            if len(members) > 1
            for member in members
        ]
        if repeated:
            repeated_tuple = tuple(sorted(repeated, key=_occurrence_sort_key))
            observations.append(DuplicateObservation(
                category="logical-repeat",
                ecosystem=ecosystem,
                name=name,
                versions=tuple(sorted({item.version for item in repeated_tuple})),
                sources=tuple(sorted({item.source for item in repeated_tuple if item.source})),
                components=tuple(sorted({item.component for item in repeated_tuple})),
                occurrences=repeated_tuple,
                reclaimable=False,
                rationale=(
                    "The same normalized resolved identity is observed more than once. "
                    "Logical repetition does not prove duplicate physical bytes or safe removal."
                ),
            ))

        if len(versions) > 1:
            observations.append(DuplicateObservation(
                category="version-divergence",
                ecosystem=ecosystem,
                name=name,
                versions=versions,
                sources=sources,
                components=components,
                occurrences=occurrences,
                reclaimable=False,
                rationale=(
                    "Multiple resolved versions are present. Native dependency constraints/resolver semantics "
                    "must decide whether convergence is possible."
                ),
            ))

        by_version_sources: dict[str, set[str]] = defaultdict(set)
        for item in occurrences:
            if item.source:
                by_version_sources[item.version].add(item.source)
        provenance_versions = {
            version: source_set
            for version, source_set in by_version_sources.items()
            if len(source_set) > 1
        }
        if provenance_versions:
            affected_versions = tuple(sorted(provenance_versions))
            affected = tuple(
                item for item in occurrences if item.version in provenance_versions
            )
            observations.append(DuplicateObservation(
                category="provenance-divergence",
                ecosystem=ecosystem,
                name=name,
                versions=affected_versions,
                sources=tuple(sorted({item.source for item in affected if item.source})),
                components=tuple(sorted({item.component for item in affected})),
                occurrences=affected,
                reclaimable=False,
                rationale=(
                    "The same package name/version is observed from multiple source identities. "
                    "Those artifacts are not assumed interchangeable."
                ),
            ))

    category_order = {
        "logical-repeat": 0,
        "version-divergence": 1,
        "provenance-divergence": 2,
    }
    observations.sort(key=lambda item: (
        item.ecosystem,
        item.name,
        category_order.get(item.category, 99),
    ))
    return DuplicateReport(tuple(observations), coverage, len(graph.components))
