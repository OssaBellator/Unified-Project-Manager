# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- first-class Go workspace discovery/inspection and guarded workspace synchronization;
- package.json workspace inspection plus native pnpm workspace ownership;
- manifest-aware Cargo workspace ownership and local workspace diagnostics;
- shared-lock uv workspace ownership, local health, graph/SBOM scoping, and batch synchronization;
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
sh ./scripts/test-python-lock-public-provider.sh
sh ./scripts/test-python-lock-native-validated.sh
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

Public `graph`, `why`, project/fleet `impact`, native SBOM, advisory inventory/path correlation, and provider-status coverage retain provider/scope labels rather than pretending these evidence classes are identical.

Poetry/PDM share `structured-lock-dependency-graph`. Their shared query model distinguishes resolved packages from ambiguity-derived `possible_packages`; each unresolved hop is rendered as `?dependency` before conservatively traversing all candidate branches. Possible state propagates through candidate descendants so public explanations cover every package that the conservative native SBOM can intentionally admit to OSV scanning.

Path traversal is explicit and bounded rather than silently collapsed: distinct same-condition parent paths are retained, `max_paths_per_package` defaults to 64, `max_search_states` defaults to 10000, and truncation is surfaced through `paths_truncated` / `search_truncated` in JSON and shared text rendering.

Unsupported structured-lock semantics fail closed rather than falling back to an environment-dependent manager command.

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
- Yarn Berry unscoped relationship queries are root-owned and use one recursive `--all` query; selected members retain root ownership while executing from the member cwd;
- Yarn package identity preserves exact descriptors/locators, virtual packages, and workspace locators; unreachable stored resolutions are excluded from SBOM/advisory inventory;
- provider coverage and skip suppression use the same plan-derived ownership model, so members are not simultaneously “served” and “unsupported.”

### Cargo

UPM does not treat “nested below a `[workspace]` manifest” as sufficient membership proof.

- explicit `[workspace].members` paths/globs define the discovered member set, subject to `[workspace].exclude`;
- a root `[package]` is itself a workspace member;
- when a root package has no explicit members list, discovered in-root path dependencies are followed transitively as Cargo's automatic-membership fallback;
- `package.workspace` is root/consistency evidence for already-proven membership, not an independent membership grant.

An unrelated nested Cargo project with its own lockfile remains an independent graph owner. Unmatched member patterns become local workspace-health warnings. Contradictory ownership becomes an error/blocker before native graph execution.

### uv

uv workspaces are modeled as one resolver state with one shared root `uv.lock`.

- `[tool.uv.workspace].members` / `exclude` establish static ownership;
- missing shared locks, overlapping ownership, and nested included uv workspaces fail closed and surface through local status health;
- unscoped graph/provider queries read the root lock once and report all proven members as covered;
- selecting a member promotes the read to the root lock but retains the selected project name/version, so `why`/`impact` traverse only that member's reachable package subgraph;
- selected CycloneDX/SPDX export admits only registry packages reachable from the selected member and never relabels local/editable/path/git/url sources as PyPI packages;
- `install --all` / `sync --all` collapse a uv workspace to one root `uv sync --all-packages`; reproducible sync adds `--locked`;
- applied batch execution uses the ordinary mutation-receipt path, producing one shared-lock receipt rather than per-member mutations.

### Poetry/PDM

Poetry/PDM plans own the exact Python component whose authoritative `poetry.lock` or `pdm.lock` they parse. They are not workspace-root promotion mechanisms.

The Python adapter's broad `resolved_packages` observations are suppressed for provider-owned components before native SBOM construction. The certainty-aware structured-lock provider then re-adds only reachable registry identities, preventing orphan lock records or ambiguous candidates from leaking back into native inventory as unconditional packages.

## Advisory model

Advisory scanning is explicit because OSV scanning may use network access.

Implemented layers include:

- preview-first project and fleet OSV-Scanner plans;
- temporary CycloneDX scan artifacts;
- correct distinction between OSV exit code 1 (findings) and scanner failure;
- provider-backed `audit --native` inventory whose Go/Cargo queries are forced offline, npm/pnpm SBOM queries are lockfile-only, Yarn Berry relationship inventory is network-disabled and project-state-preserving, and uv/Poetry/PDM inventory is static;
- dependency-path correlation for npm, pnpm, Yarn Berry, Cargo, Go, uv, Poetry, and PDM;
- pnpm advisory path evidence preserves alias, workspace-project, scope, and dedupe metadata;
- Yarn advisory paths retain exact locator/virtual/workspace relationship identity and are scoped to reachable stored resolutions;
- uv workspace advisory paths come from the shared lock but retain the member project path that reaches the affected package;
- Poetry/PDM resolved findings retain marker/optional path conditions from the same graph that produced the scanned BOM;
- Poetry/PDM direct and transitive ambiguity-derived findings are reported as `possible-via-ambiguous-lock-reference` with full candidate paths containing `?dependency` hops;
- when one locked Poetry/PDM package occurrence has both a resolved path and a possible alternative path, advisory correlation emits one consolidated impact containing both path classes rather than duplicate findings;
- versioned persisted advisory evidence at `.upm/audits/osv.json`;
- evidence fingerprints bound to the exact scanned SBOM;
- local evidence states: absent, current-clean, current-vulnerable, stale, native-inventory-unverified, invalid;
- policy fields for requiring current advisory evidence, maximum evidence age, and known-vulnerability budgets;
- automatic persistence of valid public audit outcomes (clean or vulnerable), never scanner failures.

Ordinary status/policy evaluation uses persisted local evidence and does not perform a hidden advisory scan or silently re-run provider inventory.

## SBOM interoperability

CycloneDX 1.7 and SPDX 2.3 are public formats.

- registry PURLs are emitted only where provenance supports them;
- Go selected-module evidence can add authoritative module identities and relationships;
- npm delegates package identity/relationships to npm's native `--package-lock-only` SBOM. Exact workspace selection prunes sibling workspaces without changing the authoritative root document identity;
- pnpm delegates package identity/relationships to pnpm's native `--lockfile-only` SBOM. Whole workspaces use native split output; selected members use exact path filters;
- named-registry PURL qualifiers produced by pnpm are preserved;
- Yarn Berry contributes only locators reachable from active project/workspace roots; npm-protocol resolutions may become npm PURLs, while workspace/file/git/patch and other non-registry sources remain non-registry;
- Cargo relationships are admitted only where static lock identity supports trustworthy registry endpoints;
- uv may establish PyPI identities directly from registry sources in authoritative `uv.lock`; selected workspace SBOMs are member-reachability scoped, while ambiguous/conditional relationships remain omitted rather than flattened;
- Poetry/PDM admit reachable registry packages in unconditional, conditional, or ambiguity-possible inventory states; possible state propagates through candidate descendants while conditional/ambiguous/unresolved/non-registry edges never become unconditional dependency relationships;
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

The runtime available to this implementation session cannot materialize the entire private branch as a local checkout, so full-suite claims are kept conservative. The repository contains layered local validation scripts rather than GitHub Actions.

Focused reconstructed/local validation completed for:

- pnpm graph/impact parsing, workspace ownership, exact executable use, and logical occurrence metadata;
- pnpm native SBOM split/filter planning plus CycloneDX/SPDX merge behavior;
- real local npm lock-only graph and native SBOM workspace behavior using npm 10.9.2;
- Cargo workspace ownership across explicit members, excludes, automatic path-dependency fallback, `package.workspace` non-membership behavior, and unrelated nested projects (**7 focused filesystem tests passed**);
- Yarn Berry execution compatibility against a simulated Yarn 2.4.3 runtime, retaining network refusal, telemetry suppression, immutable cache, temporary install state, and resolved-binary execution (**1 focused test passed**);
- current Poetry/PDM reachability hardening: **5/5 reconstructed tests passed** for conditional paths, direct ambiguity, transitive possible branches, same-condition path multiplicity/path caps, and search-state truncation;
- separate reconstructed checks passed for transitive possible query/advisory correlation, resolved+possible advisory consolidation, and shared possible-path text rendering.

An earlier Poetry/PDM reconstructed run exposed a serializer mismatch: `PythonLockPath.to_dict()` returned tuple-valued nodes/markers although the command-neutral query contract treated the dictionaries as JSON-ready. That was fixed so the serializer emits explicit lists.

The repository regression suite additionally covers uv shared-lock ownership, Yarn Berry graph/impact/why/SBOM/advisory/fleet behavior, exact-SBOM audit evidence, public Poetry/PDM graph/why/impact/SBOM/provider-status/advisory routing, structured-lock path budgets, text rendering, and advisory consolidation. These are included in local aggregate scripts, but the latest full branch has not been materialized and executed end-to-end in this runtime.

## Important remaining gaps

The next highest-value work is:

1. make mixed-ecosystem project/root component representation in aggregate SBOMs more explicit and uniform across providers;
2. deepen package/cache provenance before any reclaim recommendation is automated;
3. model source/API/runtime reachability separately from dependency-graph impact rather than upgrading dependency evidence into exploitability claims;
4. validate more of the very large branch in one materialized checkout when the execution environment can expose private branch bytes;
5. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
