# Architecture

## Product boundary

Unified Project Manager is a **control plane over native project/package managers**, not a universal package manager or resolver.

Native ecosystems retain authority for:

- dependency resolution and version selection;
- native manifests, locks, checksum files, and workspace semantics;
- package caches/stores;
- toolchain behavior;
- project mutation.

UPM contributes a common orchestration and observation layer above those sources of truth.

```text
public entrypoint
 |
 +-- discovery ----------------> ProjectGraph
 |                                 components / managers
 |                                 manifests / native state
 |                                 direct deps / resolved observations
 |                                 toolchain requirements
 |
 +-- status -------------------> cheap composed read-only view
 |                                 doctor health
 |                                 policy
 |                                 snapshot state
 |                                 native verifier coverage
 |                                 cache-integrity coverage
 |
 +-- doctor -------------------> structural/version/snapshot findings
 |                                 + optional deep installed-state traversal
 |
 +-- policy -------------------> project and registered-project enforcement
 |
 +-- native verification -----> non-mutating semantic checks
 |
 +-- cache integrity ----------> project cache verification
 |                                 shared-store read-only checks
 |                                 preview-first cache maintenance verification
 |
 +-- operation planner --------> preview-first native mutation plans
 +-- repair planner -----------> safe locked/frozen resync plans only
 +-- native exec -------------> manager-scoped argv escape hatch
 +-- task planner ------------> upm.toml DAGs + native task fallback
 |
 +-- native graph ------------> authoritative live graph/inventory
 |                                 Go selected build list / edges / why
 |                                 module-requirement impact
 |
 +-- registry ----------------> ~/.upm/projects.json
 |                                 fleet status / policy / inventory
 |                                 duplicates / impact / storage
 |
 +-- storage -----------------> project artifacts + shared native caches
 |
 +-- snapshot ----------------> .upm/state.json SHA-256 baseline
 |
 +-- exporters ---------------> CycloneDX 1.7
```

Specialized command families are dispatched from the public entrypoint into focused modules. This avoids turning one parser/executor file into the architecture.

## Normalized model

The common model contains only observations that can be represented honestly across ecosystems:

- component ecosystem, path, and stable key;
- native manager and ownership provenance;
- native manifest/state-file names;
- toolchain requirements;
- direct dependency name, requirement text, and scope;
- concrete resolved package records where authoritative native state supports that interpretation;
- adapter metadata and parse/read errors;
- structured findings;
- explicit command/task/verification/native-graph plans and results.

UPM deliberately does **not** define a universal lockfile.

## Adapter boundary

Adapters own detection and static inspection. They do not execute package managers.

Current adapters:

- Node — `package.json`, manager ownership, scripts, direct dependency sections, npm v2/v3 lock inventory;
- Python — `pyproject.toml`, dependency groups, Poetry tables, requirements files, uv/Poetry/PDM lock inventory;
- Rust — Cargo manifests/workspace dependency declarations and `Cargo.lock` inventory;
- Go — `go.mod` declarations plus `go.sum` checksum-state metadata.

Execution and live graph queries live in separate layers so parser code never becomes a hidden resolver/runner.

## Manager ownership and ambiguity

Mutation and arbitrary native execution are blocked when UPM cannot identify one authoritative manager safely.

Examples include:

- malformed manifests;
- conflicting manager-specific lock/state files;
- manifest manager vs lockfile manager mismatch;
- contradictory Node manager declarations;
- multiple Python manager configurations;
- ambiguous component selectors.

The invariant is simple: **if authority is ambiguous, UPM reports it instead of guessing**.

## Integrity is layered

“Corruption” is not one condition. UPM separates several integrity layers because each has different evidence and repair semantics.

### 1. Static structural health

`doctor` inspects parseable native state, manager ownership, lock/state conflicts, dependency divergence, executable availability, toolchain/version constraints, and integrity snapshots.

No native dependency resolver is reimplemented here.

### 2. Portable observation snapshot

`.upm/state.json` records reviewed project-state paths, sizes, SHA-256 hashes, and component identity.

It answers “did observed native project state change?” It does not answer “is this dependency graph semantically valid?”

### 3. Native semantic verification

`upm verify` delegates semantics UPM should not recreate, but only when a documented non-mutating command is configured.

Current examples:

- npm CI dry-run with scripts/audit/funding disabled;
- Bun frozen dry-run;
- `uv lock --check`;
- `pdm lock --check`;
- locked Cargo metadata;
- `go mod tidy -diff`.

The executor resolves the exact native binary first and executes that path, avoiding a second PATH lookup that could select a different executable.

### 4. Installed-state drift

`doctor --deep` traverses installed state only where UPM can make a sufficiently reliable comparison today:

- npm physical `node_modules` package locations/versions;
- local Python `.venv` `dist-info` metadata.

False positives are avoided when lockfiles can contain optional/platform/group-specific packages that are not expected in every environment.

### 5. Package-cache/store integrity

Cache integrity is separate again.

- Go project-context cache verification delegates to `go mod verify` using a temporary adjacent modfile/sum pair so real project files are not rewritten. The Go command may populate shared-cache metadata.
- pnpm shared-store checking uses `pnpm store status`, modeled as non-mutating.
- npm shared-cache verification is preview-first because `npm cache verify` also garbage-collects unneeded cache data.

Unsupported managers remain explicit coverage gaps.

## Cache-integrity coverage and policy

`status` reports cache-integrity coverage without executing checks.

Coverage currently distinguishes:

- pnpm `shared-store-status` — supported, read-only;
- Go `isolated-project-cache-verify` — authoritative project-context verification, may populate shared cache metadata;
- npm `shared-cache-maintenance-verify` — authoritative verification with cache maintenance side effects;
- unsupported manager — no configured authoritative mechanism.

Policy can require coverage using `require_cache_integrity_verification = true`. Evaluating that policy never runs the cache verifier.

## Preview/apply boundary

Any operation UPM knows may mutate project or shared cache state is preview-first.

This includes:

- package add/remove/install/sync;
- initialization;
- repair;
- configured arbitrary project tasks;
- manager-scoped `upm exec`;
- npm shared-cache maintenance verification.

Read-only queries such as status, doctor, graph inspection, pnpm store status, and storage measurement do not require `--apply`.

UPM does not promise transactional rollback once a native manager begins mutating state.

## Go semantics and workspace isolation

Go is the clearest example of why the abstraction must remain leaky.

`go.sum` is checksum state, not the selected build list. It may retain entries not selected by the current graph.

UPM therefore uses different native sources for different questions:

- `go list -mod=readonly -m -json all` — selected module build list and module metadata;
- `go mod graph` — module requirement edges and required versions;
- `go mod why -m` — package-import reason for a module;
- `go mod tidy -diff` — project module-file semantic consistency;
- `go mod verify` — downloaded module-cache content verification.

Because UPM currently models individual `go.mod` files as components, component-scoped native Go verification/graph/why queries set `GOWORK=off`. A surrounding `go.work` cannot silently change the component graph. Explicit Go workspace modeling is future work.

## Native selected-module graph

The Go native graph layer keeps distinct:

- logical module path/version;
- selected version;
- version required by each graph edge;
- whether an edge source corresponds to a selected module version;
- versioned replacements;
- local replacements;
- Go version;
- module and go.mod sums where provided;
- VCS origin metadata where provided;
- machine-local directories/go.mod paths for diagnostic native inventory.

Machine-local cache paths are not used as portable SBOM identity.

## Impact analysis

`impact --native` computes reverse reachability through **selected module requirement edges**.

It reports:

- direct module dependents;
- transitive module dependents;
- paths back to the main module;
- replacement-aware identity.

This is deliberately labeled **module-requirement impact**. It is not source-level, API-symbol, package-import, or runtime-call impact.

`projects impact --native` applies the same semantics across explicitly registered repositories and retains project/component context.

## Storage model

Storage accounting is observation, not deletion planning.

### Project-local roots

Current roots:

- Node `node_modules`;
- Python `.venv` / `__pypackages__`;
- Cargo `target`.

### Machine-wide native cache/store roots

Current providers:

- Go — `GOMODCACHE`, `GOCACHE` from `go env`;
- npm — configured cache path from npm;
- pnpm — `pnpm store path`;
- uv — `uv cache dir`;
- Cargo — `CARGO_HOME/registry` and `CARGO_HOME/git`.

The scanner does not follow symlinks. Inode identities are shared across roots during a scan so hardlinked physical bytes are counted once where the filesystem exposes stable inode information.

The output explicitly does **not** call measured bytes reclaimable. Safe cleanup requires ownership, recency, provenance, and ecosystem-specific retention semantics that are not yet modeled.

## Policy

Policy lives in `upm.toml`; it is read-only enforcement.

Current rules:

- required lock/checksum state;
- required integrity snapshot;
- required non-mutating native-verifier coverage;
- required cache-integrity coverage;
- manager allow/deny sets;
- doctor warning/error budgets.

Project and fleet policy use the same evaluation semantics. Invalid policy configuration is an error; missing policy is permissive.

## Unified status

`status` intentionally stays cheap.

It composes:

- components/ecosystems/managers;
- dependency observation counts;
- doctor health;
- policy;
- snapshot presence;
- native verifier coverage;
- cache-integrity coverage;
- optional project-local storage.

It does not automatically run live native graphs or cache integrity commands. Those remain explicit because they may be expensive, access shared state, populate caches, or perform maintenance.

## Native manager escape hatch

`upm exec` exists because the common vocabulary should not try to wrap every native subcommand.

It retains important UPM safety properties:

1. select one unambiguous component;
2. identify its authoritative manager;
3. construct argv without a shell;
4. resolve the exact manager executable;
5. preview by default;
6. execute only with `--apply`;
7. run post-command doctor verification unless disabled.

UPM does not claim arbitrary native subcommands are semantically safe merely because they pass through this escape hatch.

## Tasks

`upm.toml` task DAGs use argv arrays, root-relative working directories, descriptions, and dependency edges.

The planner rejects:

- shell command strings;
- root escapes;
- unknown dependencies;
- cycles.

Native fallback currently maps Node package scripts, Cargo core tasks, and Go build/test/vet/run tasks.

## Registry and fleet

The user-level registry stores only roots explicitly registered by the user; there is no home-directory crawler.

Fleet capabilities include:

- status/health;
- policy;
- resolved/native inventory;
- duplicate/version divergence views;
- module-requirement impact;
- project artifact storage accounting.

Machine-wide shared caches are measured once at machine scope rather than attributed repeatedly to projects.

## CycloneDX

The CycloneDX 1.7 exporter operates on concrete authoritative inventory.

Static lock-resolved inventory produces registry Package URLs where provenance supports it. Git/path/local records use deterministic UPM identities instead of fabricated registry identity.

Native Go enrichment:

- uses selected module versions, not `go.sum` rows;
- uses canonical Go Package URL namespace/name structure for versioned modules;
- preserves local replacements as versionless UPM identities;
- carries stable module sums, Go version, indirect flag, and VCS origin as properties;
- excludes machine-specific absolute cache paths from portable identity.

Dependency relationships are emitted only for native graph edges UPM can map to selected module identities.

## Current deliberate limitations

- no universal dependency resolver or lockfile;
- no heuristic parsing of opaque manager formats merely to claim support;
- Go `go.work` is not yet a first-class workspace component;
- native transitive graph ingestion is currently deepest for Go;
- no source/API symbol impact analysis;
- no destructive deduplication or generic cache cleanup;
- cache-integrity coverage is incomplete for several managers;
- installed-state deep checks remain ecosystem-specific;
- SPDX export is not yet implemented;
- advisory/provenance vulnerability correlation is future work.

## Direction

The next valuable layers are not more aliases for native commands. They are:

1. first-class workspace models where ecosystems have workspace semantics that change resolution;
2. additional authoritative native graph providers;
3. richer cache/store provenance, recency, and ownership before any cleanup planning;
4. broader installed-environment integrity checks;
5. advisory/provenance correlation over authoritative identities;
6. SPDX and richer relationship export;
7. source/package-level impact only when an ecosystem can provide trustworthy relationship data.

The architectural rule remains: **preserve native semantics, expose uncertainty, and never turn an observation into a destructive action without an ecosystem-specific proof of safety.**
