from __future__ import annotations

from pathlib import Path
from typing import Any

from .audit_status import evaluate_audit_status
from .doctor import diagnose
from .models import ProjectGraph
from .policy import evaluate_policy
from .provider_registry import provider_summary
from .receipt_chain import CHAIN_PATH, validate_receipt_chain
from .receipt_history import latest_receipt_drift
from .workspace_health import workspace_findings

SNAPSHOT_PATH = Path('.upm/state.json')


def local_evidence_status(
    graph: ProjectGraph,
    *,
    deep: bool = False,
    advisory_max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Compose local control-plane evidence without spawning native graph/scanner commands.

    Deep doctor traversal is optional but remains local filesystem inspection.
    Provider capability is descriptive only; no native provider is executed.
    Advisory state is read from persisted evidence only.
    """
    doctor = diagnose(graph, deep=deep)
    workspace_health = workspace_findings(graph)
    policy = evaluate_policy(graph, deep=deep)
    advisory = evaluate_audit_status(graph, max_age_seconds=advisory_max_age_seconds)
    receipts = latest_receipt_drift(graph)
    providers = provider_summary(graph)
    chain_path = graph.root / CHAIN_PATH
    chain = validate_receipt_chain(graph.root) if chain_path.is_file() else None

    workspace_errors = sum(1 for finding in workspace_health if finding.severity == 'error')
    workspace_warnings = sum(1 for finding in workspace_health if finding.severity == 'warning')
    blockers = []
    if doctor.errors:
        blockers.append('doctor-errors')
    if workspace_errors:
        blockers.append('workspace-errors')
    if not policy.passed:
        blockers.append('policy-violations')
    if advisory.state == 'current-vulnerable':
        blockers.append('known-vulnerabilities')
    if receipts.state in {'drifted', 'invalid', 'invalid-latest-history'}:
        blockers.append('receipt-state')
    if chain is not None and not chain.valid:
        blockers.append('receipt-chain')

    return {
        'root': str(graph.root),
        'network_executed': False,
        'native_provider_execution': False,
        'scanner_execution': False,
        'summary': {
            'components': len(graph.components),
            'ecosystems': sorted({component.ecosystem for component in graph.components}),
            'managers': sorted({component.manager for component in graph.components if component.manager}),
            'doctor_errors': doctor.errors,
            'doctor_warnings': doctor.warnings,
            'workspace_errors': workspace_errors,
            'workspace_warnings': workspace_warnings,
            'policy_passed': policy.passed,
            'advisory_state': advisory.state,
            'receipt_state': receipts.state,
            'receipt_chain_state': (
                'absent' if chain is None else ('valid' if chain.valid else 'invalid')
            ),
            'relationship_provider_coverage': {
                'supported': providers['supported_components'],
                'total': providers['total_components'],
            },
            'blockers': blockers,
        },
        'doctor': doctor.to_dict(),
        'workspace_health': [finding.to_dict() for finding in workspace_health],
        'policy': policy.to_dict(),
        'advisory_evidence': advisory.to_dict(),
        'mutation_receipts': receipts.to_dict(),
        'mutation_receipt_chain': (
            chain.to_dict() if chain is not None else {
                'present': False,
                'valid': None,
                'path': CHAIN_PATH.as_posix(),
                'authenticated': False,
            }
        ),
        'relationship_providers': providers,
        'integrity_snapshot': {
            'path': SNAPSHOT_PATH.as_posix(),
            'exists': (graph.root / SNAPSHOT_PATH).is_file(),
        },
        'workspaces': [workspace.to_dict(graph.root) for workspace in graph.workspaces],
    }
