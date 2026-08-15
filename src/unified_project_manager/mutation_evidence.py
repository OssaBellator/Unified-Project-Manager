from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .dependency_delta import DependencyDelta, dependency_delta
from .models import ProjectGraph
from .receipt_execution import ReceiptExecution, execute_plans_with_receipt


@dataclass(frozen=True)
class MutationEvidence:
    execution: ReceiptExecution
    dependency_delta: DependencyDelta

    @property
    def succeeded(self) -> bool:
        return self.execution.succeeded

    def to_dict(self) -> dict[str, Any]:
        return {
            'succeeded': self.succeeded,
            'execution': self.execution.to_dict(),
            'dependency_delta': self.dependency_delta.to_dict(),
            'resolver_interpretation': False,
        }


def execute_plans_with_evidence(
    graph: ProjectGraph,
    operation: str,
    plans: Iterable[object],
    execute: Callable[[object], object],
    *,
    extra_paths: Iterable[str | Path] = (),
    receipt_path: str | Path | None = None,
) -> MutationEvidence:
    execution = execute_plans_with_receipt(
        graph,
        operation,
        plans,
        execute,
        extra_paths=extra_paths,
        receipt_path=receipt_path,
    )
    delta = dependency_delta(graph, execution.after_graph)
    return MutationEvidence(execution, delta)
