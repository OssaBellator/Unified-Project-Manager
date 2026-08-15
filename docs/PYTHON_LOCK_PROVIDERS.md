# Structured Poetry and PDM lock-provider contract

This document describes the lower-level Poetry/PDM relationship provider implemented on `feature/initial-control-plane`. It is intentionally **not yet advertised as a public native provider**. Public promotion should happen only after graph, why, impact, SBOM, advisory, provider-coverage, and failure behavior are routed together.

## Why static lock evidence

UPM does not need to invoke an environment-dependent `poetry show` or `pdm list` command merely to recover relationships already present in structured TOML lock state.

The lower-level provider reads:

- `poetry.lock` for components owned by Poetry;
- `pdm.lock` for components owned by PDM.

It uses Python's standard-library `tomllib`. No subprocess, environment activation, network access, package installation, or project mutation occurs.

Native manifests and lockfiles remain authoritative. This provider is a normalized observation layer, not a resolver.

## Identity

A locked package occurrence retains:

- normalized package name for matching;
- original name;
- locked version;
- source kind;
- lock groups where available;
- a distinct internal package id.

Source kinds are deliberately provenance-sensitive. Registry-backed packages may later become PyPI PURLs. Git, path/directory, URL/file, editable, and other local/non-registry records are not relabeled as registry packages.

## Relationship resolution

Lock dependency records are parsed differently by manager but normalized to one edge model:

- Poetry `[package.dependencies]` records retain version text, markers, optionality, and multi-constraint records;
- PDM dependency strings retain the package name, requirement text, and PEP-508 marker text.

UPM does **not** run a second resolver over these requirements.

A dependency name resolves to an internal target only when the lock contains exactly one candidate with that normalized name. If multiple locked candidates exist, the edge remains explicit ambiguity:

- `target_id = null`;
- all candidate package ids are retained;
- `ambiguous = true`;
- impact/why must not select a candidate by version guessing.

This is intentionally conservative. It can under-resolve a lock whose manager knows more context than UPM has modeled, but it does not fabricate certainty.

## Project roots

The provider creates a synthetic project root for each component and connects normalized direct manifest dependencies to lock candidates using the same exact-one-candidate rule.

This lets relationship queries answer project-to-package paths without pretending the project itself is a registry package.

## Conditional reachability

Marker-bearing and optional edges are graph evidence, not unconditional reachability.

The certainty-aware reachability layer retains, per path:

- exact package path;
- marker expressions accumulated along that path;
- optional-edge count;
- whether the path is conditional.

A package can therefore have both an unconditional path and a marker-qualified path. Public `why` / `impact` promotion should expose that distinction rather than collapsing both into a single boolean “used” answer.

If an ambiguous dependency reference is itself reachable from the project and matches the user's query, the reachability report returns the ambiguity and candidate ids without manufacturing a package path.

## SBOM behavior

The lower-level CycloneDX/SPDX merger uses project-root reachability to avoid turning unrelated/orphan lock records into scan targets.

Only reachable registry-backed packages receive PyPI PURLs.

Relationship admission is stricter than package admission:

- uniquely resolved + unconditional registry-to-registry edge: may become a dependency relationship;
- marker-bearing edge: package identities may be present, but the edge is omitted from unconditional SBOM dependency relationships;
- ambiguous edge: omitted from dependency relationships;
- non-registry endpoint: not represented as a PyPI relationship merely for graph completeness.

CycloneDX records omitted conditional/ambiguous relationship counts as provider properties. SPDX omits those relationships.

## Public promotion checklist

Do not add Poetry/PDM to `provider_registry` until all of the following share this same model:

1. `graph --native` exposes resolved and ambiguous edges with manager/scope labels;
2. `why --native` exposes conditional paths and ambiguity evidence;
3. `impact --native` uses the same certainty-aware reachability report;
4. fleet impact carries the same semantics;
5. `sbom --native` uses reachable registry package identity and does not flatten markers/ambiguity;
6. `audit --native` scans the exact same SBOM identity and reuses retained lock-graph evidence for advisory paths;
7. project/fleet status advertises coverage only after the public routes above exist;
8. provider failure/unsupported lock strategy remains explicit rather than silently falling back to a heuristic or environment-dependent CLI command.

## Current local regression slice

Run:

```sh
sh ./scripts/test-python-lock-native-current.sh
```

The focused suite covers:

- Poetry transitive relationships;
- PDM PEP-508 markers;
- duplicate locked-name ambiguity;
- non-registry source identity;
- conditional versus unconditional paths;
- reachable ambiguity reporting;
- reachable-only SBOM package identity;
- omission of conditional/ambiguous SBOM relationships.

This slice is additive and local-only; no GitHub Actions workflow is required or used.
