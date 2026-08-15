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

Poetry/PDM share `structured-lock-dependency-graph`.

Their shared reachability/query model:

- distinguishes resolved packages from ambiguity-derived `possible_packages`;
- renders each unresolved hop as `?dependency` before conservatively traversing candidate branches;
- propagates possible state through candidate descendants;
- preserves marker/optional conditions and distinct same-condition paths;
- uses explicit `max_paths_per_package=64` and `max_search_states=10000` defaults;
- surfaces `paths_truncated` / `search_truncated` in JSON and shared text rendering;
- reuses the same validated graph results for exact-SBOM advisory correlation.

Unsupported structured-lock semantics fail closed rather than falling back to an environment-dependent manager command.

## Fleet native inventory and duplicate correlation

`projects inventory --native` and `projects duplicates --native` route all eight public provider families.

Provider-specific occurrence meaning remains visible:

- npm keeps logical occurrence refs/depth/directness;
- pnpm keeps workspace project, alias, dependency scope, depth/directness, and dedupe metadata;
- Yarn includes only active-root-reachable stored locators and excludes project roots/inactive stored records;
- Cargo uses locked package IDs;
- uv uses universal-lock package identity;
- Poetry/PDM use certainty-aware reachable structured-lock inventory and label rows `unconditional`, `conditional`, or `possible`;
- Poetry/PDM orphan lock records are excluded rather than becoming fleet package observations.

Duplicate grouping remains observation-only. `reclaimable=false` is explicit.

## SBOM interoperability and project topology

CycloneDX 1.7 and SPDX 2.3 are public formats.

Registry PURLs are emitted only where provenance supports them. Provider-specific uncertainty is retained: Yarn uses reachable stored resolutions; uv and Poetry/PDM do not flatten conditional/ambiguous relationships into unconditional edges; local/git/path identities are not relabeled as registry artifacts.

Aggregate SBOMs also represent mixed-project topology explicitly:

- CycloneDX has one deterministic aggregate `metadata.component` application root plus one application anchor per discovered UPM component;
- SPDX has one aggregate `APPLICATION` package plus one `APPLICATION` package per component and aggregate `CONTAINS` relationships;
- anchor identity and aggregate naming are clone-location-independent;
- provider merges preserve the topology;
- generic normalized inventory does not manufacture component→package dependency edges.

Application anchors are topology-only and are excluded from advisory package counts without imposing a blanket `type=library` requirement on other valid CycloneDX scan targets.

See `SBOM_PROJECT_COMPONENTS.md`.

## Advisory model

Advisory scanning is explicit because OSV scanning may use network access.

Implemented layers include:

- preview-first project and fleet OSV-Scanner plans;
- provider-backed `audit --native` inventory following each provider's local/offline contract;
- exact CycloneDX document retention and fingerprinted `.upm/audits/osv.json` evidence;
- dependency-path correlation for npm, pnpm, Yarn Berry, Cargo, Go, uv, Poetry, and PDM;
- Poetry/PDM conditional and ambiguity-derived path evidence with `?dependency` hops;
- consolidated advisory impact when one locked package occurrence has both resolved and possible alternative paths;
- local clean/vulnerable/stale/native-unverified/invalid evidence states;
- project/fleet policy fields for advisory evidence/freshness/vulnerability budgets.

Ordinary status/policy evaluation uses persisted local evidence and does not perform hidden scans or hidden provider execution.

## Cache/storage safety and provenance

The cache subsystem separates:

- `storage` — physical measurement only;
- `provenance` — package-to-cache attribution without reclamation inference;
- `check` — non-mutating integrity checks where available;
- `verify` — verification that may perform manager maintenance;
- `prune` — manager-defined removal of unused/unreferenced data;
- `clean` — explicit full-cache removal.

### Public physical cache provenance

```sh
upm cache provenance
upm cache provenance --manager go
upm cache provenance --manager cargo
upm cache provenance --closed-universe --json
```

The command operates over explicitly registered projects and supports only the managers where current native evidence gives sufficiently trustworthy physical package identity.

**Go**:

- source attribution begins from the selected module directory reported by the native offline graph;
- the directory must resolve under measured `GOMODCACHE`;
- selected-version `.info`, `.mod`, `.zip`, and `.ziphash` download artifacts are derived by reusing the already-escaped native physical path;
- UPM does not reimplement Go path escaping;
- noncanonical physical layouts are not guessed;
- `GOCACHE` build bytes remain measured storage but outside selected-module package attribution.

**Cargo**:

- attribution begins from `manifest_path` returned by `cargo metadata --locked --offline`;
- only `CARGO_HOME/registry/src` and `CARGO_HOME/git/checkouts` are package-source attribution roots;
- `registry/index`, `registry/cache`, `git/db`, workspace/path dependencies, and unrelated locations are not mislabeled package-source ownership.

The report distinguishes a user assertion that the registered project universe is closed from whether the current storage/native observation completed successfully. Missing projects, provider failures, uncovered applicable provider plans, missing/ambiguous cache roots, or inconsistent byte measurements prevent a complete-observation claim.

Safety fields remain invariant:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv cache/store internals remain without per-package physical attribution rather than being heuristically parsed merely to claim coverage.

Implemented maintenance plans still prefer manager-defined operations: pnpm store prune, uv cache prune, npm full cache clean, and separate Go build/module cache clean operations. Provenance does not create `rm -rf` targets.

See `CACHE_PROVENANCE.md`.

## Current validation state

The runtime available to this implementation session cannot materialize the entire private branch as a local checkout, so full-suite claims remain conservative. The repository contains layered local validation scripts rather than GitHub Actions.

Focused reconstructed/local validation completed for:

- real local npm lock-only graph/native SBOM workspace behavior using npm 10.9.2;
- Cargo workspace ownership across explicit members/excludes/path-dependency fallback and unrelated nested projects (**7 focused filesystem tests passed**);
- Yarn Berry execution compatibility against a simulated Yarn 2.4.3 runtime plus shared execution-policy checks;
- Poetry/PDM reachability hardening (**5/5 reconstructed tests passed**) covering conditional paths, direct ambiguity, transitive possible branches, same-condition path multiplicity/path caps, and search-state truncation;
- separate reconstructed Poetry/PDM query/advisory consolidation and possible-path rendering checks;
- all-provider fleet core (**4/4 reconstructed checks passed**);
- mixed-project SBOM anchors (**5/5 reconstructed checks passed**);
- cache physical mapping (**5/5 reconstructed filesystem checks passed**) covering Go selected download artifacts/fail-closed path handling/inode accounting and Cargo source-root admission/rejection;
- cache provenance report semantics (**6/6 reconstructed checks passed**) covering manager totals, build-cache exclusion, no-reclaim invariants, closure invalidation, provider failure/skip incompleteness, and measurement inconsistency.

Committed local regressions extend beyond those reconstructed slices and are included by `check-all-local-latest.sh`. The latest full branch has not been materialized and executed end-to-end in this runtime.

## Important remaining gaps

The next highest-value work is now:

1. deepen physical cache provenance only where a manager-native identity contract can support it; do not reverse-engineer opaque npm/pnpm/uv internals merely to inflate coverage;
2. model source/API/runtime reachability separately from dependency-graph impact rather than upgrading dependency evidence into exploitability claims;
3. validate more of the very large branch in one materialized checkout when the execution environment can expose private branch bytes;
4. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
