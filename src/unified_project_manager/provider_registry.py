from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from .models import Component, ProjectGraph

NetworkMode = Literal['none', 'offline', 'may-use-network']
MutationMode = Literal['none', 'project-read-only']


@dataclass(frozen=True)
class NativeProviderCapability:
    provider: str
    ecosystem: str
    manager: str
    evidence: str
    graph_scope: str
    why_scope: str | None
    impact_scope: str | None
    source: str
    execution: bool
    network: NetworkMode
    mutation: MutationMode
    supports_graph: bool = True
    supports_why: bool = True
    supports_impact: bool = True
    supports_sbom_relationships: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderCoverage:
    component: str
    ecosystem: str
    manager: str | None
    provider: NativeProviderCapability | None
    reason: str | None

    @property
    def supported(self) -> bool:
        return self.provider is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            'component': self.component,
            'ecosystem': self.ecosystem,
            'manager': self.manager,
            'supported': self.supported,
            'provider': self.provider.to_dict() if self.provider else None,
            'reason': self.reason,
        }


GO_PROVIDER = NativeProviderCapability(
    provider='go-modules',
    ecosystem='go',
    manager='go',
    evidence='authoritative selected module list + module requirement graph',
    graph_scope='module-requirement',
    why_scope='package-import-chain',
    impact_scope='module-requirement',
    source='go list -m -json all + go mod graph / go mod why -m with GOPROXY=off',
    execution=True,
    network='offline',
    mutation='project-read-only',
)

NPM_PROVIDER = NativeProviderCapability(
    provider='npm-lock-tree',
    ecosystem='node',
    manager='npm',
    evidence='npm logical dependency tree reconstructed from package-lock state',
    graph_scope='logical-dependency-tree',
    why_scope='logical-dependency-tree',
    impact_scope='logical-dependency-tree',
    source='npm ls --all --json --package-lock-only',
    execution=True,
    network='none',
    mutation='project-read-only',
)

CARGO_PROVIDER = NativeProviderCapability(
    provider='cargo-metadata',
    ecosystem='rust',
    manager='cargo',
    evidence='locked Cargo resolve graph with package IDs, dependency kinds, and targets',
    graph_scope='locked-offline-dependency-graph',
    why_scope='locked-offline-dependency-graph',
    impact_scope='locked-offline-dependency-graph',
    source='cargo metadata --format-version 1 --locked --offline',
    execution=True,
    network='offline',
    mutation='project-read-only',
)

UV_PROVIDER = NativeProviderCapability(
    provider='uv-lock',
    ecosystem='python',
    manager='uv',
    evidence='static universal uv.lock package/relationship graph with explicit fork ambiguity',
    graph_scope='universal-lock-dependency-graph',
    why_scope='universal-lock-dependency-graph',
    impact_scope='universal-lock-dependency-graph',
    source='uv.lock',
    execution=False,
    network='none',
    mutation='none',
)

PROVIDERS = (GO_PROVIDER, NPM_PROVIDER, CARGO_PROVIDER, UV_PROVIDER)


def provider_for_component(component: Component) -> tuple[NativeProviderCapability | None, str | None]:
    if component.ecosystem == 'go' and component.manager == 'go':
        return GO_PROVIDER, None
    if component.ecosystem == 'node' and component.manager == 'npm':
        if not any(name in component.lockfiles for name in ('package-lock.json', 'npm-shrinkwrap.json')):
            return None, 'npm native graph requires package-lock.json or npm-shrinkwrap.json'
        return NPM_PROVIDER, None
    if component.ecosystem == 'rust' and component.manager == 'cargo':
        if 'Cargo.lock' not in component.lockfiles:
            return None, 'Cargo native graph requires Cargo.lock for locked/offline resolution'
        return CARGO_PROVIDER, None
    if component.ecosystem == 'python' and component.manager == 'uv':
        if 'uv.lock' not in component.lockfiles:
            return None, 'uv relationship graph requires uv.lock'
        return UV_PROVIDER, None
    return None, 'no authoritative native relationship provider is configured for this component'


def provider_coverage(graph: ProjectGraph) -> list[ProviderCoverage]:
    result: list[ProviderCoverage] = []
    for component in graph.components:
        provider, reason = provider_for_component(component)
        result.append(ProviderCoverage(
            component=component.key(graph.root),
            ecosystem=component.ecosystem,
            manager=component.manager,
            provider=provider,
            reason=reason,
        ))
    return result


def provider_summary(graph: ProjectGraph) -> dict[str, Any]:
    coverage = provider_coverage(graph)
    supported = [item for item in coverage if item.supported]
    return {
        'total_components': len(coverage),
        'supported_components': len(supported),
        'unsupported_components': len(coverage) - len(supported),
        'providers': sorted({item.provider.provider for item in supported if item.provider}),
        'network_modes': sorted({item.provider.network for item in supported if item.provider}),
        'coverage': [item.to_dict() for item in coverage],
    }
