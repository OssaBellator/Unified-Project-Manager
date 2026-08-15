# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- Go, package.json/pnpm, Cargo, and uv workspace ownership models;
- structural/deep health, policy, integrity snapshots, native verification, and evidence-aware status;
- preview-first package-manager delegation, repair, initialization, tasks, exec, workspace sync, and cache maintenance;
- mutation receipts plus receipt history/drift and optional local receipt-chain anchoring;
- project/fleet status, policy, inventory, duplicate, impact, storage, and advisory views;
- machine-wide cache/store measurement;
- public read-only Go/Cargo physical cache provenance for explicitly registered projects;
- CycloneDX 1.7 and SPDX 2.3 export with deterministic mixed-project application topology;
- preview-first OSV-Scanner advisory scanning with exact scanned-SBOM evidence retention;
- opt-in Go package-import advisory reachability kept separate from dependency/runtime/exploitability claims;
- relationship-provider coverage surfaced in local status without hidden provider execution.

No GitHub Actions workflows are used. Validation remains local and script-driven. The aggregate entrypoint is:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused slices include:

```sh
sh ./scripts/check.sh
sh ./scripts/test-integration.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
sh ./scripts/test-sbom-project-components.sh
sh ./scripts/test-cache-provenance.sh
sh ./scripts/test-go-import-reachability.sh
```

## Native relationship providers

`--native` relationship analysis has eight public provider families:

- **Go** — selected modules, module requirement graph, package-import `why`, replacements, module provenance; cache-only/offline by default through `GOPROXY=off`;
- **npm** — workspace-aware lock-only logical dependency tree through npm plus native lockfile-only CycloneDX/SPDX provenance;
- **pnpm** — workspace-aware lock-only logical dependency tree preserving alias/project/dedupe occurrence evidence plus native lockfile-only CycloneDX/SPDX provenance;
- **Yarn Berry 2+** — exact descriptor/locator and virtual/workspace identity from native `yarn info`; network disabled, install state redirected, cache immutable, and reachable-only SBOM/advisory identity;
- **Cargo** — `cargo metadata --locked --offline`, package IDs/kinds/targets, with workspace ownership derived from Cargo manifests rather than arbitrary nesting;
- **uv** — static universal project/workspace graph from authoritative `uv.lock`, preserving marker/fork ambiguity and selected-member scope instead of guessing;
- **Poetry** — validated static `poetry.lock` relationships with optional/marker conditions, explicit ambiguity, reachable-only SBOM identity, and no subprocess/network/mutation;
- **PDM** — validated static `pdm.lock` relationships with PEP-508 markers, explicit ambiguity, reachable-only SBOM identity, and no subprocess/network/mutation.

Public `graph`, `why`, project/fleet `impact`, native SBOM, advisory inventory/path correlation, provider-status coverage, and fleet native inventory/duplicate correlation retain provider/scope labels rather than pretending these evidence classes are identical.

### Poetry/PDM uncertainty model

Poetry/PDM share `structured-lock-dependency-graph`. Their shared reachability/query model distinguishes resolved packages from ambiguity-derived `possible_packages`, renders unresolved hops as `?dependency`, propagates possible state through candidate descendants, preserves marker/optional conditions and distinct paths, and surfaces explicit path/search truncation. The same validated graph results are reused for exact-SBOM advisory correlation.

Unsupported structured-lock semantics fail closed rather than falling back to an environment-dependent manager command.

## Fleet native inventory and duplicate correlation

`projects inventory --native` and `projects duplicates --native` route all eight public provider families while retaining provider-specific occurrence meaning. Duplicate grouping remains observation-only with `reclaimable=false`.

## SBOM interoperability and project topology

CycloneDX 1.7 and SPDX 2.3 are public formats. Registry PURLs are emitted only where provenance supports them, and provider-specific uncertainty is retained rather than flattened.

Aggregate SBOMs represent mixed-project topology explicitly:

- CycloneDX has one deterministic aggregate application root plus one application anchor per discovered UPM component;
- SPDX has one aggregate `APPLICATION` package plus one `APPLICATION` package per component and aggregate `CONTAINS` relationships;
- anchor identity and aggregate naming are clone-location-independent;
- provider merges preserve the topology;
- generic normalized inventory does not manufacture component→package dependency edges.

Application anchors are topology-only and are excluded from advisory package counts without imposing a blanket `type=library` requirement on other valid CycloneDX scan targets.

See `SBOM_PROJECT_COMPONENTS.md`.

## Advisory and reachability model

Advisory scanning is explicit because OSV scanning may use network access. Implemented layers include preview-first project/fleet plans, provider-backed `audit --native`, exact scanned CycloneDX retention/fingerprinting, dependency-path correlation across all eight public provider families, structured-lock conditional/ambiguity evidence, and local evidence/policy states.

### Go package-import reachability

A stronger source/import layer is now public for Go as an explicit audit enrichment:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

The flag requires full `--native` inventory so source evidence is queried only for vulnerable Go module impacts already correlated to the retained native scan inventory.

The enrichment uses `go mod why -m` through UPM's `GOPROXY=off` wrapper and emits separate states:

- `package-import-reachable`;
- `not-package-import-reachable`;
- `query-failed`.

The Go command's package graph is any-build-tag and can include test imports, so each row records:

```text
build_constraints = any-tags
current_build_configuration_reachability = not-evaluated
test_imports_may_contribute = true
api_reachability = not-evaluated
runtime_reachability = not-evaluated
exploitability = not-established
persisted = false
```

Preview never executes the import query. Applied queries are report-only and are not written into `.upm/audits/osv.json`; ordinary status does not replay them as durable evidence. Query failures do not invalidate independently valid OSV scan evidence.

See `REACHABILITY_EVIDENCE.md`.

### Reachability classes still not implemented

UPM does **not** currently provide a public provider for:

- current-build-configuration reachability;
- vulnerable API/symbol reachability;
- runtime/data-flow reachability;
- exploitability determination.

Dependency presence, dependency paths, and Go package-import paths must not be promoted into those stronger claims.

Ordinary status/policy evaluation does not perform hidden scans, dependency-provider execution, or source/import queries.

## Cache/storage safety and provenance

The cache subsystem separates storage measurement, physical provenance, integrity checks, maintenance verification, prune, and clean.

`upm cache provenance` is public for Go and Cargo only. Go attribution uses native-reported module directories plus selected-version download artifacts derived from the already-escaped physical path. Cargo attribution uses canonical `registry/src/<index>/<crate-version>` and `git/checkouts/<repo>/<revision>` physical source objects. Legitimate multi-crate Cargo git containers are measured once; conflicting registry identities or competing Go physical identities make an observation incomplete.

Safety fields remain invariant:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv cache/store internals remain without per-package physical attribution rather than being heuristically parsed merely to claim coverage.

See `CACHE_PROVENANCE.md`.

## Current validation state

The runtime available to this implementation session cannot materialize the entire private branch as a local checkout, so full-suite claims remain conservative. The repository contains layered local validation scripts rather than GitHub Actions.

Focused reconstructed/local validation completed for:

- real local npm lock-only graph/native SBOM workspace behavior using npm 10.9.2;
- Cargo workspace ownership across explicit members/excludes/path-dependency fallback and unrelated nested projects (**7 focused filesystem tests passed**);
- Yarn Berry execution compatibility against a simulated Yarn 2.4.3 runtime plus shared execution-policy checks;
- Poetry/PDM reachability hardening (**5/5 reconstructed tests passed**);
- separate Poetry/PDM query/advisory consolidation and possible-path rendering checks;
- all-provider fleet core (**4/4 reconstructed checks passed**);
- mixed-project SBOM anchors (**5/5 reconstructed checks passed**);
- initial cache physical mapping (**5/5 reconstructed filesystem checks passed**);
- additional Cargo physical-object checks for one-object multi-crate git checkout grouping and noncanonical shallow-checkout refusal;
- cache provenance report semantics (**7/7 reconstructed checks passed**), plus separate identity-precision checks;
- Go package-import reachability core (**6/6 reconstructed checks passed**) including any-build-tag evidence semantics, positive/negative results, query failure/skip, deduplication, and non-Go filtering.

Project/fleet Go import-reachability CLI regressions are committed and included in the native-security/aggregate local scripts, but the full private checkout has not been executed end-to-end in this runtime.

## Important remaining gaps

The next highest-value work is now:

1. add stronger source/API/runtime reachability only where an ecosystem-native evidence contract can support it; the existing Go package-import layer must not be upgraded into current-build, symbol, runtime, or exploitability claims;
2. deepen physical cache provenance only where a manager-native identity contract can support it; Cargo's documented cache internals are not treated as a stable reverse-engineering API, and opaque npm/pnpm/uv internals remain unsupported;
3. validate more of the very large branch in one materialized checkout when the execution environment can expose private branch bytes;
4. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
