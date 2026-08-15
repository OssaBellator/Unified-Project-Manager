from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .native_graph import NativeGraphError, NativeGraphResult


@dataclass(frozen=True)
class NativeImpact:
    component: str
    query: str
    module: str
    effective_name: str
    selected_version: str | None
    direct_dependents: tuple[str, ...]
    transitive_dependents: tuple[str, ...]
    root_paths: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_native_impact(result: NativeGraphResult, module: str) -> list[NativeImpact]:
    """Analyze reverse reachability in the selected module requirement graph.

    This is intentionally module-level dependency impact. It does not claim to
    represent package imports, source references, API use, or runtime call paths.
    Only requirement edges emitted by selected source module versions are used.
    """
    if not result.succeeded:
        raise NativeGraphError(
            f"Cannot analyze impact for failed native graph {result.plan.component}: {result.stderr}"
        )

    selected_modules = {item.name: item for item in result.modules}
    main_names = {item.name for item in result.modules if item.main}
    targets = [
        item
        for item in result.modules
        if not item.main and module in {item.name, item.effective_name}
    ]

    reverse: dict[str, set[str]] = {}
    for edge in result.edges:
        if edge.source_selected:
            reverse.setdefault(edge.target_name, set()).add(edge.source_name)

    impacts: list[NativeImpact] = []
    for target in sorted(targets, key=lambda item: item.name):
        direct = tuple(sorted(name for name in reverse.get(target.name, set()) if name not in main_names))
        dependents: set[str] = set()
        root_paths: set[tuple[str, ...]] = set()
        visited = {target.name}
        queue: list[tuple[str, tuple[str, ...]]] = [(target.name, (target.name,))]

        while queue:
            current, reverse_path = queue.pop(0)
            for predecessor in sorted(reverse.get(current, set())):
                new_reverse_path = (*reverse_path, predecessor)
                if predecessor in main_names:
                    root_paths.add(tuple(reversed(new_reverse_path)))
                    continue
                if predecessor not in selected_modules:
                    continue
                dependents.add(predecessor)
                if predecessor in visited:
                    continue
                visited.add(predecessor)
                queue.append((predecessor, new_reverse_path))

        impacts.append(
            NativeImpact(
                component=result.plan.component,
                query=module,
                module=target.name,
                effective_name=target.effective_name,
                selected_version=target.effective_version,
                direct_dependents=direct,
                transitive_dependents=tuple(sorted(dependents)),
                root_paths=tuple(sorted(root_paths)),
            )
        )
    return impacts
