from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .discovery import discover
from .models import ProjectGraph
from .receipts import MutationReceipt, build_mutation_receipt, capture_project_state, write_mutation_receipt


@dataclass(frozen=True)
class ReceiptExecution:
    results: tuple[object, ...]
    receipt: MutationReceipt
    receipt_path: Path
    after_graph: ProjectGraph

    @property
    def succeeded(self) -> bool:
        return self.receipt.succeeded

    def to_dict(self) -> dict[str, Any]:
        return {
            'succeeded': self.succeeded,
            'receipt': self.receipt.to_dict(),
            'receipt_path': str(self.receipt_path),
            'results': [
                result.to_dict(self.after_graph.root) if callable(getattr(result, 'to_dict', None)) else {
                    'returncode': getattr(result, 'returncode', None)
                }
                for result in self.results
            ],
        }


def _verification_payload(result: object, root: Path) -> dict[str, Any] | None:
    verification = getattr(result, 'verification', None)
    if verification is None:
        return None
    to_dict = getattr(verification, 'to_dict', None)
    if callable(to_dict):
        try:
            value = to_dict()
        except TypeError:
            value = to_dict(root)
        if isinstance(value, dict):
            return value
    return None


def execute_plans_with_receipt(
    graph: ProjectGraph,
    operation: str,
    plans: Iterable[object],
    execute: Callable[[object], object],
    *,
    extra_paths: Iterable[str | Path] = (),
    receipt_path: str | Path | None = None,
) -> ReceiptExecution:
    """Execute already-approved plans and persist before/after mutation evidence.

    This function does not decide whether a command is safe or whether it should
    be previewed; those remain responsibilities of the normal plan/CLI layers.
    It records partial state even when a command returns non-zero.
    """
    before = capture_project_state(graph, extra_paths=extra_paths)
    results: list[object] = []
    commands: list[dict[str, Any]] = []
    latest_verification: dict[str, Any] | None = None

    for plan in plans:
        result = execute(plan)
        results.append(result)
        commands.append({
            'component': getattr(plan, 'component', None),
            'manager': getattr(plan, 'manager', None),
            'cwd': getattr(plan, 'cwd', '.'),
            'argv': list(getattr(plan, 'argv', ())),
            'returncode': getattr(result, 'returncode', None),
        })
        verification = _verification_payload(result, graph.root)
        if verification is not None:
            latest_verification = verification
        returncode = getattr(result, 'returncode', None)
        if isinstance(returncode, int) and returncode != 0:
            break

    after_graph = discover(graph.root)
    after = capture_project_state(after_graph, extra_paths=extra_paths)
    receipt = build_mutation_receipt(
        graph.root,
        operation,
        commands,
        before,
        after,
        verification=latest_verification,
    )
    written = write_mutation_receipt(graph.root, receipt, receipt_path)
    return ReceiptExecution(tuple(results), receipt, written, after_graph)
