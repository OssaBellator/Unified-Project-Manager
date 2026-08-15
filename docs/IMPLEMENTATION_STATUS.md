# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- first-class Go workspace discovery/inspection and guarded workspace synchronization;
- package.json workspace inspection plus native pnpm workspace ownership;
- manifest-aware Cargo workspace ownership and local workspace diagnostics;
- structural `doctor` health plus opt-in installed-state checks;
- toolchain and Node package-manager version checks;
- SHA-256 project-state snapshots;
- preview-first package-manager delegation and repair;
- workspace-aware `install --all` / `sync --all` planning;
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
- **npm** — workspace-aware lock-only logical dependency tree through npm plus native lockfile-only CycloneDX/SPDX provenance;
- **pnpm** — workspace-aware lock-only logical dependency tree preserving alias/project/dedupe occurrence evidence plus native lockfile-only CycloneDX/SPDX provenance;
- **Cargo** — `cargo metadata --locked --offline`, package IDs/kinds/targets, with workspace ownership derived from Cargo manifests rather than arbitrary nesting;
- **uv** — static universal-lock graph retaining marker/fork ambiguity instead of guessing.

Public `graph`, `why`, `impact`, fleet impact, and native SBOM routes retain provider/scope labels rather than pretending these evidence classes are identical.

## Workspace ownership

Workspace ownership is part of the provider contract rather than a CLI formatting detail.

### Go

- `go.work` / `go.work.sum` are discovered and snapshot-tracked;
- workspace inspection delegates to `go work edit -json`;
- explicit workspace graph/impact uses the selected workspace;
- normal component-scoped Go commands disable ambient workspace inheritance;
- public Go relationship queries force `GOPROXY=off`;
- `go work sync` is preview-first and records before/after hashes;
- external workspace members require explicit opt-in.

### Node

- npm/Yarn/Bun package.json workspaces are inspected from package.json declarations;
- pnpm workspace membership is inspected through pnpm rather than a fragile dependency-free YAML parser;
- `install --all` / `sync --all` collapse workspace members to one authoritative root operation where ownership is proven;
- npm relationship/SBOM member selection promotes to the root `package-lock.json` and uses an exact `--workspace ./path` selector;
- pnpm relationship queries promote members to the root `pnpm-lock.yaml`; native SBOM member selection uses an exact root-relative `--filter` path;
- provider coverage and skip suppression use the same plan-derived ownership model, so members are not simultaneously “served” and “unsupported.”

### Cargo

UPM no longer treats “nested below a `[workspace]` manifest” as sufficient membership proof. Static workspace ownership uses discovered Cargo manifests and:

- `[workspace].members` paths/globs;
- `[workspace].exclude`;
- the workspace root `[package]`, when present;
- explicit `package.workspace` pointers;
- discovered in-root local path dependencies.

An unrelated nested Cargo project with its own lockfile remains an independent graph owner. Unmatched member patterns become local workspace-health warnings. Contradictory ownership becomes an error/blocker before native graph execution.

## Advisory model

Advisory scanning is explicit because OSV scanning may use network access.

Implemented layers include:

- preview-first project and fleet OSV-Scanner plans;
- temporary CycloneDX scan artifacts;
- correct distinction between OSV exit code 1 (findings) and scanner failure;
- offline Go inventory enrichment before the network-capable scanner stage;
- dependency-path correlation for npm, pnpm, Cargo, Go, and conservative uv evidence;
- pnpm advisory path evidence preserves alias, workspace-project, scope, and dedupe metadata;
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
- npm delegates package identity/relationships to npm's native `--package-lock-only` SBOM. Exact workspace selection prunes sibling workspaces without changing the authoritative root document identity;
- pnpm delegates package identity/relationships to pnpm's native `--lockfile-only` SBOM. Whole workspaces use native split output; selected members use exact path filters;
- named-registry PURL qualifiers produced by pnpm are preserved;
- Cargo relationships are admitted only where static lock identity supports trustworthy registry endpoints;
- uv ambiguous/conditional relationships are omitted rather than flattened into unconditional edges;
- native npm/pnpm document-local refs are remapped into stable aggregate identities;
- native CycloneDX input does not downgrade UPM's aggregate CycloneDX 1.7 schema;
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

Focused reconstructed local validation completed for:

- pnpm graph/impact parsing, workspace ownership, exact executable use, and logical occurrence metadata;
- pnpm native SBOM split/filter planning plus CycloneDX/SPDX merge behavior;
- real local npm lock-only graph and native SBOM workspace behavior using npm 10.9.2;
- Cargo workspace ownership across explicit members, excludes, local path dependencies, `package.workspace`, and unrelated nested standalone projects (**5 focused filesystem tests passed**).

The focused cases are also represented as repository regression tests and included in `scripts/test-integration.sh`. GitHub Actions remains intentionally absent.

## Important remaining gaps

The next highest-value work is narrower than before:

1. add authoritative relationship/SBOM providers for Yarn/Poetry/PDM only where their native tools expose stable non-mutating evidence without heuristic lock parsing;
2. make mixed-ecosystem project/root component representation in aggregate SBOMs more explicit and uniform across providers;
3. deepen package/cache provenance before any reclaim recommendation is automated;
4. model source/API/runtime reachability separately from dependency-graph impact rather than upgrading dependency evidence into exploitability claims;
5. validate more of the very large branch in one materialized checkout when the execution environment can expose private branch bytes;
6. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
