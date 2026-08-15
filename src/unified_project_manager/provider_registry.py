from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .cargo_graph import cargo_provider_component_keys, plan_cargo_graphs
from .models import Component, ProjectGraph
from .npm_graph import npm_provider_component_keys, plan_npm_graphs
from .pnpm_graph import plan_pnpm_graphs, pnpm_provider_component_keys
from .uv_graph import plan_uv_graphs, uv_provider_component_keys
from .yarn_graph import plan_yarn_graphs, yarn_provider_component_keys

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

PNPM_PROVIDER = NativeProviderCapability(
    provider='pnpm-lock-tree',
    ecosystem='node',
    manager='pnpm',
    evidence='pnpm logical dependency tree plus native lockfile-only SBOM provenance',
    graph_scope='logical-dependency-tree',
    why_scope='logical-dependency-tree',
    impact_scope='logical-dependency-tree',
    source='pnpm list --depth Infinity --json --lockfile-only + pnpm sbom --lockfile-only',
    execution=True,
    network='none',
    mutation='project-read-only',
    supports_sbom_relationships=True,
)

YARN_PROVIDER = NativeProviderCapability(
    provider='yarn-berry-resolution-graph',
    ecosystem='node',
    manager='yarn',
    evidence='Yarn Berry stored locator/descriptor resolutions with virtual/workspace identity preserved',
    graph_scope='berry-resolution-graph',
    why_scope='berry-resolution-graph',
    impact_scope='berry-resolution-graph',
    source='yarn info --all --recursive --virtuals --json with Berry network disabled, temporary install state, and immutable cache',
    execution=True,
    network='offline',
    mutation='none',
    supports_sbom_relationships=True,
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
    evidence='static universal shared uv.lock package/relationship graph with explicit fork ambiguity',
    graph_scope='universal-lock-dependency-graph',
    why_scope='universal-lock-dependency-graph',
    impact_scope='universal-lock-dependency-graph',
    source='authoritative project/workspace uv.lock',
    execution=False,
    network='none',
    mutation='none',
)

PROVIDERS = (GO_PROVIDER, NPM_PROVIDER, PNPM_PROVIDER, YARN_PROVIDER, CARGO_PROVIDER, UV_PROVIDER)


def _declared_yarn_berry(component: Component) -> bool:
    value = component.metadata.get('package_manager_declared')
    if not isinstance(value, str) or not value.startswith('yarn@'):
        return False
    match = re.search(r'\d+', value[len('yarn@'):])
    return bool(match and int(match.group(0)) >= 2)


def provider_for_component(component: Component) -> tuple[NativeProviderCapability | None, str | None]:
    if component.ecosystem == 'go' and component.manager == 'go':
        return GO_PROVIDER, None
    if component.ecosystem == 'node' and component.manager == 'npm':
        if not any(name in component.lockfiles for name in ('package-lock.json', 'npm-shrinkwrap.json')):
            return None, 'npm native graph requires package-lock.json or npm-shrinkwrap.json at the authoritative workspace/project root'
        return NPM_PROVIDER, None
    if component.ecosystem == 'node' and component.manager == 'pnpm':
        if 'pnpm-lock.yaml' not in component.lockfiles:
            return None, 'pnpm native graph requires pnpm-lock.yaml at the authoritative workspace/project root'
        return PNPM_PROVIDER, None
    if component.ecosystem == 'node' and component.manager == 'yarn':
        if 'yarn.lock' not in component.lockfiles:
            return None, 'Yarn native graph requires yarn.lock at the authoritative project/workspace root'
        if not _declared_yarn_berry(component):
            return None, 'Yarn native graph currently requires an explicit packageManager declaration for Yarn Berry 2+'
        return YARN_PROVIDER, None
    if component.ecosystem == 'rust' and component.manager == 'cargo':
        if 'Cargo.lock' not in component.lockfiles:
            return None, 'Cargo native graph requires Cargo.lock at the authoritative workspace/project root'
        return CARGO_PROVIDER, None
    if component.ecosystem == 'python' and component.manager == 'uv':
        if 'uv.lock' not in component.lockfiles:
            return None, 'uv relationship graph requires uv.lock at the authoritative project/workspace root'
        return UV_PROVIDER, None
    return None, 'no authoritative native relationship provider is configured for this component'


def _owned_components(graph: ProjectGraph) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    try:
        npm_plans = plan_npm_graphs(graph)
        npm_owned = npm_provider_component_keys(graph, npm_plans)
    except ValueError:
        npm_owned = set()
    try:
        pnpm_plans = plan_pnpm_graphs(graph)
        pnpm_owned = pnpm_provider_component_keys(graph, pnpm_plans)
    except ValueError:
        pnpm_owned = set()
    try:
        yarn_plans = plan_yarn_graphs(graph)
        yarn_owned = yarn_provider_component_keys(graph, yarn_plans)
    except ValueError:
        yarn_owned = set()
    try:
        cargo_plans = plan_cargo_graphs(graph)
        cargo_owned = cargo_provider_component_keys(graph, cargo_plans)
    except ValueError:
        cargo_owned = set()
    try:
        uv_plans = plan_uv_graphs(graph)
        uv_owned = uv_provider_component_keys(graph, uv_plans)
    except ValueError:
        uv_owned = set()
    return npm_owned, pnpm_owned, yarn_owned, cargo_owned, uv_owned


def provider_coverage(graph: ProjectGraph) -> list[ProviderCoverage]:
    npm_owned, pnpm_owned, yarn_owned, cargo_owned, uv_owned = _owned_components(graph)
    result: list[ProviderCoverage] = []
    for component in graph.components:
        key = component.key(graph.root)
        provider, reason = provider_for_component(component)
        if key in npm_owned:
            provider, reason = NPM_PROVIDER, None
        elif key in pnpm_owned:
            provider, reason = PNPM_PROVIDER, None
        elif key in yarn_owned:
            provider, reason = YARN_PROVIDER, None
        elif key in cargo_owned:
            provider, reason = CARGO_PROVIDER, None
        elif key in uv_owned:
            provider, reason = UV_PROVIDER, None
        result.append(ProviderCoverage(
            component=key,
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
