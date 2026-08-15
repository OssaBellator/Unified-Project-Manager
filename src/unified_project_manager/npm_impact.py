from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .npm_graph import NpmGraphError, NpmGraphResult


@dataclass(frozen=True)
class NpmImpact:
    component: str
    query: str
    ref: str
    name: str
    version: str | None
    direct: bool
    direct_parent: str
    ancestor_packages: tuple[str, ...]
    root_path: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_npm_impact(result: NpmGraphResult, package: str) -> list[NpmImpact]:
    """Return logical dependency-tree paths for matching npm package occurrences.

    This is lock-tree dependency impact only. It does not claim source imports,
    API usage, physical node_modules placement, or runtime reachability.
    """
    if not result.succeeded:
        raise NpmGraphError(
            f"Cannot analyze impact for failed npm graph {result.plan.component}: {result.stderr}"
        )

    by_ref = {item.ref: item for item in result.packages}
    root_ref = f"{result.plan.component}:root"
    root_label = result.root_name or "(project root)"
    if result.root_version:
        root_label += f"@{result.root_version}"

    impacts: list[NpmImpact] = []
    for target in sorted(
        (item for item in result.packages if item.name == package),
        key=lambda item: (item.depth, item.ref),
    ):
        ancestors_reversed: list[str] = []
        parent_ref = target.parent_ref
        direct_parent = root_label
        while parent_ref and parent_ref != root_ref:
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
        root_path = (root_label, *ancestors, target_label)
        impacts.append(NpmImpact(
            component=result.plan.component,
            query=package,
            ref=target.ref,
            name=target.name,
            version=target.version,
            direct=target.direct,
            direct_parent=direct_parent,
            ancestor_packages=ancestors,
            root_path=root_path,
        ))
    return impacts
