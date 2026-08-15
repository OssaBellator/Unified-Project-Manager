from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .pnpm_graph import PnpmGraphError, PnpmGraphResult


@dataclass(frozen=True)
class PnpmImpact:
    component: str
    project: str
    query: str
    ref: str
    alias: str
    name: str
    version: str | None
    direct: bool
    scope: str
    deduped: bool
    direct_parent: str
    ancestor_packages: tuple[str, ...]
    root_path: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_pnpm_impact(result: PnpmGraphResult, package: str) -> list[PnpmImpact]:
    """Return lock-only logical dependency paths for matching pnpm occurrences.

    This is dependency-tree evidence from pnpm's lockfile-backed list command. It
    does not claim source/API/runtime reachability or physical install placement.
    """
    if not result.succeeded:
        raise PnpmGraphError(
            f"Cannot analyze impact for failed pnpm graph {result.plan.component}: {result.stderr}"
        )

    by_ref = {item.ref: item for item in result.packages}
    projects = {item.ref: item for item in result.projects}
    impacts: list[PnpmImpact] = []
    query = package.lower()
    targets = [
        item for item in result.packages
        if item.name.lower() == query or item.alias.lower() == query
    ]
    for target in sorted(targets, key=lambda item: (item.project_ref, item.depth, item.ref)):
        project = projects.get(target.project_ref)
        if project is None:
            root_label = target.project_ref
            project_path = target.project_ref
        else:
            root_label = project.name or project.path or "(project root)"
            if project.version:
                root_label += f"@{project.version}"
            project_path = project.path

        ancestors_reversed: list[str] = []
        parent_ref = target.parent_ref
        direct_parent = root_label
        while parent_ref and parent_ref != target.project_ref:
            parent = by_ref.get(parent_ref)
            if parent is None:
                break
            label = parent.name + (f"@{parent.version}" if parent.version else "")
            if not ancestors_reversed:
                direct_parent = label
            ancestors_reversed.append(label)
            parent_ref = parent.parent_ref

        ancestors = tuple(reversed(ancestors_reversed))
        target_label = target.name + (f"@{target.version}" if target.version else "")
        impacts.append(PnpmImpact(
            component=result.plan.component,
            project=project_path,
            query=package,
            ref=target.ref,
            alias=target.alias,
            name=target.name,
            version=target.version,
            direct=target.direct,
            scope=target.scope,
            deduped=target.deduped,
            direct_parent=direct_parent,
            ancestor_packages=ancestors,
            root_path=(root_label, *ancestors, target_label),
        ))
    return impacts
