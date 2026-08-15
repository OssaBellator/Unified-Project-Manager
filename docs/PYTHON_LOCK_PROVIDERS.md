# Structured Poetry and PDM lock-provider contract

This document describes the lower-level Poetry/PDM relationship provider implemented on `feature/initial-control-plane`. It is intentionally **not yet advertised as a public native provider**. Public promotion should happen only after graph, why, impact, fleet impact, SBOM, advisory, provider-coverage, and failure behavior are routed together.

## Why static lock evidence

UPM does not need to invoke an environment-dependent `poetry show` or `pdm list` command merely to recover relationships already present in structured TOML lock state.

The lower-level provider reads:

- `poetry.lock` for components owned by Poetry;
- `pdm.lock` for components owned by PDM.

It uses Python's standard-library `tomllib`. No subprocess, environment activation, network access, package installation, or project mutation occurs.

Native manifests and lockfiles remain authoritative. This provider is a normalized observation layer, not a resolver.

## Provider boundary

`python_lock_provider.py` centralizes the pre-promotion contract:

- Poetry provider id: `poetry-lock`;
- PDM provider id: `pdm-lock`;
- shared scope: `structured-lock-dependency-graph`;
- provider ownership is derived from validated lock plans;
- validated execution is the only high-level execution path;
- generic adapter `resolved_packages` are suppressed for provider-owned components when constructing a future native SBOM baseline.

That last rule is important. The general Python adapter records every package in a Poetry/PDM lock as a broad static observation. Native Poetry/PDM inventory must not merge the certainty-aware provider result on top of those observations, because doing so could reintroduce orphan or ambiguous packages that structured reachability intentionally excluded.

This boundary remains internal until the full promotion checklist below is satisfied.

## Identity

A locked package occurrence retains:

- normalized package name for matching;
- original name;
- locked version;
- source kind;
- lock groups where available;
- a distinct internal package id.

Source kinds are deliberately provenance-sensitive. Registry-backed packages may become PyPI PURLs. Git, path/directory, URL/file, editable, and other local/non-registry records are not relabeled as registry packages.

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

A dependency with zero candidates is a different state from ambiguity. It is retained as an unresolved reference and must not be reported as if multiple possible targets existed.

## Project roots

The provider creates a synthetic project root for each component and connects normalized direct manifest dependencies to lock candidates using the same exact-one-candidate rule.

Direct conditions are preserved before graph construction:

- PEP 621 optional dependency groups become optional root edges;
- Poetry `{ optional = true }` direct dependencies become optional root edges;
- optional Poetry dependency groups become optional root edges;
- Poetry direct `markers`, `python`, and `platform` constraints remain attached to the normalized requirement so the certainty-aware traversal retains a conditional path.

This lets relationship queries answer project-to-package paths without pretending the project itself is a registry package or silently upgrading optional/marker-qualified declarations into unconditional reachability.

## Conditional and possible reachability

Marker-bearing and optional edges are graph evidence, not unconditional reachability.

The certainty-aware reachability layer retains, per path:

- exact package path;
- marker expressions accumulated along that path;
- optional-edge count;
- whether the path is conditional.

A package can therefore have both an unconditional path and a marker-qualified path. Public `why` / `impact` promotion should expose that distinction rather than collapsing both into a single boolean “used” answer.

`python_lock_queries.py` provides one command-neutral serialization contract for future `why`, project `impact`, and fleet impact routing. A conditional match or reachable ambiguity is marked uncertain; an ambiguity can count as a query match without producing a fabricated resolved package path. The query object also states explicitly that dependency reachability is not source/API/runtime reachability or exploitability.

Reachable ambiguous references are not discarded from scan inventory. Their candidate package identities are admitted as **possible** reachability so a vulnerability scanner does not miss a candidate merely because UPM refuses to guess which lock occurrence the manager selected. Those candidates are annotated as ambiguous/possible and are not connected by a fabricated dependency relationship.

If an ambiguous dependency reference itself matches a `why`/`impact` query, the reachability report returns the ambiguity and candidate ids without manufacturing a package path.

## SBOM behavior

The lower-level CycloneDX/SPDX merger uses project-root reachability to avoid turning unrelated/orphan lock records into scan targets. Before certainty-aware package identities are merged, generic static lock observations owned by the structured provider are removed so they cannot leak excluded records back into the native document.

Only reachable registry-backed packages receive PyPI PURLs. Reachability has three useful inventory states:

- **unconditional** — at least one unconditional project path exists;
- **conditional** — only marker/optional-qualified resolved paths exist;
- **possible** — the package is a candidate behind a reachable ambiguous lock reference.

Relationship admission is stricter than package admission:

- uniquely resolved + unconditional registry-to-registry edge: may become a dependency relationship;
- marker-bearing or optional edge: package identities may be present, but the edge is omitted from unconditional SBOM dependency relationships;
- ambiguous edge: candidates may remain scan-visible as possible inventory, but the edge is omitted;
- unresolved edge: omitted and distinguished from ambiguity;
- non-registry endpoint: omitted rather than represented as a PyPI relationship merely for graph completeness.

CycloneDX records provider uncertainty explicitly through properties such as conditional/ambiguous reachability and counts for conditional, ambiguous, unresolved, and non-registry edges omitted from unconditional relationships. SPDX 2.3 does not have an equivalent property mechanism in the current model, so it retains the conservative package subset and omits relationships that are not unconditional.

Because generic SPDX package records do not currently preserve per-component occurrence provenance, future public SPDX routing must construct its base document from `suppress_python_lock_static_inventory(...)` before merging structured-lock results. That prevents an identical PURL observed by an unrelated component from being accidentally removed while the provider-owned static seed is replaced.

## Exact advisory inventory boundary

`python_lock_native_inventory.py` now provides an internal fail-closed CycloneDX inventory object for the advisory seam. It deliberately retains three things together:

- the structured provider plans;
- the validated `PythonLockGraphResult` objects used to build inventory;
- the exact CycloneDX document produced from those results.

Assembly verifies that result order/identity matches the planned provider evidence and refuses to expose a BOM when any structured provider result failed. This mirrors the existing native advisory evidence rule: the graph used for dependency-path explanations must be the same graph retained alongside the exact BOM that was scanned, not a second reconstruction performed after the scanner returns.

This inventory object is **not yet wired into public `audit --native`**. Keeping it internal avoids a partial promotion where security scanning claims Poetry/PDM support before project/fleet query routes and provider-status coverage share the same uncertainty semantics.

## Public promotion checklist

Do not add Poetry/PDM to `provider_registry` until all of the following share this same model:

1. `graph --native` exposes resolved, unresolved, and ambiguous edges with manager/scope labels;
2. `why --native` exposes conditional paths and ambiguity evidence through the shared query contract;
3. `impact --native` uses the same certainty-aware query result;
4. fleet impact carries the same semantics;
5. `sbom --native` suppresses generic static lock observations, uses unconditional/conditional/possible reachability correctly, and does not flatten markers, optionality, or ambiguity;
6. `audit --native` scans the exact retained structured-lock BOM and reuses the same retained lock-graph results for advisory paths;
7. project/fleet status advertises coverage only after the public routes above exist;
8. provider failure/unsupported lock strategy remains explicit rather than silently falling back to a heuristic or environment-dependent CLI command.

## Current local regression slice

Run the comprehensive validated slice:

```sh
sh ./scripts/test-python-lock-native-validated.sh
```

Focused provider/SBOM/query/audit-boundary checks are:

```sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
```

The focused suite covers:

- provider ids, scope, ownership, and generic-static-inventory suppression;
- supported lock-contract validation;
- Poetry transitive relationships;
- PDM PEP-508 markers;
- duplicate locked-name ambiguity;
- non-registry source identity;
- direct optional and marker conditions from Python manifests;
- conditional versus unconditional paths;
- multiple retained dependency paths;
- one shared future query contract for project/fleet relationship explanations;
- reachable ambiguity reporting;
- ambiguous candidates retained as possible scan inventory without fake edges;
- reachable-only SBOM package identity;
- separate conditional/ambiguous/unresolved/non-registry omission evidence;
- conservative CycloneDX and SPDX relationships;
- fail-closed exact CycloneDX inventory with retained graph evidence.

Focused reconstructed/local validation in this implementation environment includes the provider-boundary tests (**3 passed**), five structured-lock SBOM uncertainty scenarios, four direct manifest-condition normalization scenarios, three shared query-contract scenarios, and three exact inventory-assembly scenarios. The full private feature branch is still not materialized in this runtime, so those focused results are not presented as a whole-branch test run.

This validation is local-only; no GitHub Actions workflow is required or used.
