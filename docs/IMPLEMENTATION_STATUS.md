# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- first-class Go workspace discovery/inspection and guarded workspace synchronization;
- package.json workspace inspection plus native pnpm workspace ownership;
- structural `doctor` health plus opt-in installed-state checks;
- toolchain and Node package-manager version checks;
- SHA-256 project-state snapshots;
- preview-first package-manager delegation and repair;
- workspace-aware `install --all` / `sync --all` planning that collapses authoritative Node workspace ownership;
- automatic mutation receipts for applied package operations, batch operations, exec, repair, init, and Go workspace sync;
- receipt-history/drift validation and local status blockers;
- preview-first project task DAGs plus supported native tasks;
- manager-scoped argv-only native execution;
- project/fleet status, policy, inventory, duplicate, impact, and storage views;
- machine-wide cache/store measurement and package/cache provenance layers;
- cache integrity/maintenance operations with explicit mutation classes;
- CycloneDX 1.7 and SPDX 2.3 export;
- preview-first OSV-Scanner advisory scanning with persisted SBOM-bound evidence;
- relationship-provider coverage surfaced in local status without hidden provider execution.

No GitHub Actions workflows are used. Validation remains local and script-driven through:

```sh
sh ./scripts/check.sh
sh ./scripts/test-integration.sh
```

## Native relationship providers

`--native` relationship analysis now has five provider families:

- **Go** — selected modules, module requirement graph, package-import `why`, replacements, module provenance; cache-only/offline by default through `GOPROXY=off`;
- **npm** — lock-only logical dependency tree through npm itself, including duplicate logical occurrences;
- **pnpm** — lock-only logical dependency tree through `pnpm list --lockfile-only`, preserving workspace-project and dedupe occurrence evidence; native pnpm CycloneDX/SPDX supplies package provenance;
- **Cargo** — `cargo metadata --locked --offline`, preserving package IDs, dependency kinds/targets, and workspace ownership;
- **uv** — static universal-lock graph retaining marker/fork ambiguity instead of guessing.

Public `graph`, `why`, `impact`, fleet impact, and native SBOM routes retain provider/scope labels rather than pretending these evidence classes are identical.

## Go workspace model

Go workspaces are first-class rather than ambient process state.

- `go.work` / `go.work.sum` are discovered and snapshot-tracked;
- workspace inspection delegates to `go work edit -json`;
- explicit workspace graph/impact uses the selected workspace;
- normal component-scoped Go commands disable ambient workspace inheritance;
- public Go relationship queries force `GOPROXY=off`;
- `go work sync` is preview-first and records before/after hashes;
- external workspace members require explicit opt-in.

## Node workspace model

Node workspaces distinguish manifest declarations from authoritative manager ownership.

- npm/Yarn/Bun package.json workspaces are inspected conservatively from package.json declarations;
- pnpm workspace membership is inspected through pnpm rather than a dependency-free YAML approximation;
- `install --all` / `sync --all` collapse workspace members to one authoritative root operation where ownership is proven;
- pnpm relationship queries promote a selected member to the root `pnpm-lock.yaml` graph;
- provider capability coverage applies the same workspace ownership, so members are not falsely reported unsupported merely because they have no local lockfile;
- native pnpm SBOM selection uses exact path filters, not package-name filters that could broaden selection.

## Advisory model

Advisory scanning is explicit because OSV scanning may use network access.

Implemented layers include:

- preview-first project and fleet OSV-Scanner plans;
- temporary CycloneDX scan artifacts;
- correct distinction between OSV exit code 1 (findings) and scanner failure;
- offline Go inventory enrichment before the network-capable scanner stage;
- dependency-path correlation for npm, pnpm, Cargo, Go, and conservative uv relationship evidence where routed;
- versioned persisted advisory evidence at `.upm/audits/osv.json`;
- evidence fingerprints bound to the exact scanned SBOM;
- local evidence states: absent, current-clean, current-vulnerable, stale, native-inventory-unverified, invalid;
- policy fields for requiring current advisory evidence, maximum evidence age, and known-vulnerability budgets;
- automatic persistence of valid public audit outcomes (clean or vulnerable), never scanner failures.

Ordinary status/policy evaluation uses persisted local evidence and does not perform a hidden advisory scan.

## SBOM interoperability

CycloneDX 1.7 and SPDX 2.3 are public formats.

- registry PURLs are emitted only where provenance supports them;
- Go selected-module evidence can add authoritative module identities and relationships;
- npm/Cargo relationships are admitted only when static native identity already supports the endpoints;
- uv ambiguous/conditional relationships are omitted rather than flattened into unconditional edges;
- pnpm delegates package identity to pnpm's own lockfile-only SBOM emitter for both CycloneDX and SPDX;
- pnpm workspace SBOMs use native split/filter behavior and merged document-local refs are remapped to stable UPM identities;
- named-registry PURL qualifiers produced by pnpm are preserved;
- SPDX namespaces are recomputed after native document merge so the namespace remains content-derived.

SPDX 3.x is intentionally not claimed through a version-string translation; it requires a dedicated object model.

## Cache/storage safety

The cache subsystem intentionally separates:

- `storage` — measurement only;
- `check` — non-mutating integrity checks where available;
- `verify` — verification that may perform manager maintenance;
- `prune` — manager-defined removal of unused/unreferenced data;
- `clean` — explicit full-cache removal.

Implemented explicit maintenance plans include pnpm store prune, uv cache prune, npm full cache clean, and separate Go build/module cache clean operations.

Storage measurements are never converted into generic deletion targets. Cache provenance/accounting can distinguish attributed from unattributed bytes but does not label unattributed bytes reclaimable.

## Current validation state

The runtime available to this implementation session cannot materialize the entire private branch as a local checkout, so full-suite claims are kept conservative. The repository contains:

```sh
sh ./scripts/check.sh
sh ./scripts/test-integration.sh
```

Focused new pnpm graph/SBOM cores were also executed locally in reconstructed dependency-minimal mirrors, covering parsing, workspace ownership, exact executable use, logical impact paths, native split/filter planning, CycloneDX merge, and SPDX merge. GitHub Actions remains intentionally absent.

## Important remaining gaps

The next highest-value work is now narrower:

1. eliminate residual provider skip-accounting inconsistencies in recursive workspace queries so ownership and skip lists are derived from the same provider plan;
2. add authoritative relationship providers for Yarn/Poetry/PDM only where their native tools expose stable, non-mutating evidence without heuristic lock parsing;
3. extend advisory-path correlation to the new pnpm provider using the same logical occurrence model;
4. deepen package/cache provenance before any reclaim recommendation is automated;
5. improve mixed-ecosystem SBOM root/project-component modeling so project roots are represented consistently across providers;
6. model source/API/runtime reachability separately from dependency-graph impact rather than upgrading dependency evidence into exploitability claims;
7. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
