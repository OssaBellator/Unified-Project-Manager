from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .models import ProjectGraph


def normalize_package_name(ecosystem: str, name: str) -> str:
    value = name.lower()
    if ecosystem == "python":
        return re.sub(r"[-_.]+", "-", value)
    return value


def why(graph: ProjectGraph, package: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for component in graph.components:
        expected = normalize_package_name(component.ecosystem, package)
        for dependency in component.dependencies:
            if normalize_package_name(component.ecosystem, dependency.name) != expected:
                continue
            matches.append({
                "component": component.key(graph.root),
                "ecosystem": component.ecosystem,
                "manager": component.manager,
                "name": dependency.name,
                "requirement": dependency.requirement,
                "scope": dependency.scope,
            })
    return matches


def why_resolved(graph: ProjectGraph, package: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for component in graph.components:
        expected = normalize_package_name(component.ecosystem, package)
        for resolved in component.resolved_packages:
            if normalize_package_name(component.ecosystem, resolved.name) != expected:
                continue
            matches.append({
                "component": component.key(graph.root),
                "ecosystem": component.ecosystem,
                "manager": component.manager,
                "name": resolved.name,
                "version": resolved.version,
                "source": resolved.source,
                "location": resolved.location,
            })
    return matches


def duplicates(graph: ProjectGraph) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for component in graph.components:
        for dependency in component.dependencies:
            normalized = normalize_package_name(component.ecosystem, dependency.name)
            groups[(component.ecosystem, normalized)].append({
                "component": component.key(graph.root),
                "name": dependency.name,
                "requirement": dependency.requirement,
                "scope": dependency.scope,
            })

    result: list[dict[str, Any]] = []
    for (ecosystem, normalized), occurrences in sorted(groups.items()):
        if len(occurrences) < 2:
            continue
        components = {item["component"] for item in occurrences}
        requirements = {item["requirement"] for item in occurrences if item["requirement"]}
        result.append({
            "ecosystem": ecosystem,
            "name": normalized,
            "occurrences": occurrences,
            "classification": "cross-component" if len(components) > 1 else "multiple-declarations",
            "version_divergence": len(requirements) > 1,
        })
    return result


def resolved_duplicates(graph: ProjectGraph) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for component in graph.components:
        for package in component.resolved_packages:
            normalized = normalize_package_name(component.ecosystem, package.name)
            groups[(component.ecosystem, normalized)].append({
                "component": component.key(graph.root),
                "name": package.name,
                "version": package.version,
                "source": package.source,
                "location": package.location,
            })

    result: list[dict[str, Any]] = []
    for (ecosystem, normalized), occurrences in sorted(groups.items()):
        if len(occurrences) < 2:
            continue
        versions = {item["version"] for item in occurrences}
        components = {item["component"] for item in occurrences}
        result.append({
            "ecosystem": ecosystem,
            "name": normalized,
            "occurrences": occurrences,
            "classification": "multiple-resolved-versions" if len(versions) > 1 else ("cross-component" if len(components) > 1 else "repeated-resolution"),
            "version_divergence": len(versions) > 1,
        })
    return result
