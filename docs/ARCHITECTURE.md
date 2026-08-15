# Architecture

## Product boundary

UPM is a local-first control plane over native package managers, toolchains, manifests, dependency state, installed environments, project workflows, and explicitly registered repositories. It is deliberately **not** a universal dependency resolver.

```text
public entrypoint
 |
 +-- discovery ------------> normalized ProjectGraph
 |                              |
 |                              +-- components / managers
 |                              +-- manifests / native state
 |                              +-- direct dependencies
 |                              +-- resolved packages where trustworthy
 |                              +-- toolchain requirements
 |
 +-- status ---------------> composed read-only project view
 |                              +-- doctor health
 |                              +-- project policy
 |                              +-- integrity snapshot state
 |                              +-- native verifier coverage
 |                              +-- optional deep/storage scans
 |
 +-- doctor ---------------> structural / version / snapshot findings
 |                              +-- --deep installed-state findings
 |
 +-- policy ---------------> upm.toml enforcement
 |                              +-- project policy
 |                              +-- registered-project fleet policy
 |
 +-- native verifier ------> non-mutating manager/toolchain checks
 |
 +-- cache verifier -------> authoritative cache-content checks
 |                              +-- currently Go module cache
 |
 +-- package planner ------> explicit native CommandPlan(s)
 |                              +-- preview by default
 |                              +-- refuse ambiguous ownership
 |
 +-- native exec ----------> manager-scoped escape hatch
 |                              +-- argv only, no shell
 |                              +-- preview by default
 |                              +-- post-command doctor verification
 |
 +-- repair planner -------> safely mapped native sync plans only
 |
 +-- task planner ---------> upm.toml DAGs + supported native tasks
 |                              +-- argv only, no shell strings
 |                              +-- preview by default
 |
 +-- native graph ---------> authoritative ecosystem graph queries
 |                              +-- Go selected build list / edges / why / impact
 |
 +-- registry -------------> ~/.upm/projects.json
 |                              +-- fleet health / policy / inventory
 |                              +-- duplicates / impact / storage
 |
 +-- snapshot -------------> .upm/state.json SHA-256 baseline
 |
 +-- exporters ------------> CycloneDX 1.7
```

The public `upm` console script and `python -m unified_project_manager` route through `entrypoint.py`. Specialized command families are dispatched to focused entrypoint modules rather than growing one monolithic parser. The established package/health CLI remains available behind that public entrypoint.

## Core model

The normalized model stores information only when it can be represented without pretending ecosystems are identical:

- ecosystem and component path/key;
- inferred native package manager and manager provenance;
- native manifest/state-file names;
- runtime/toolchain requirements;
- direct dependency name, native requirement text, and scope;
- concrete resolved package name/version/source/location when authoritative native state supports that observation;
- adapter metadata and parse/read errors;
- structured doctor/policy findings;
- explicit package, task, native-exec, verification, and graph plans/results.

Native resolvers remain authoritative for exact resolution and mutation.

## Adapter boundary

Ecosystem adapters own detection and inspection:

- `detect(directory)`: decide whether a directory is a project root for the ecosystem;
- `inspect(directory)`: translate native project state into a normalized `Component`.

Execution is deliberately separate. Operation planners convert normalized components into explicit native argv; runners own executable lookup, subprocess execution, output capture, and post-operation verification.

Current adapters:

- **Node**: `package.json`; npm/pnpm/Yarn/Bun ownership; scripts; npm v2/v3 concrete lock inventory;
- **Python**: `pyproject.toml`, dependency groups, Poetry tables, requirements files; uv/Poetry/PDM TOML lock inventory;
- **Rust**: Cargo manifests/workspace dependencies and `Cargo.lock` inventory;
- **Go**: `go.mod` module/direct dependency/toolchain declarations and `go.sum` checksum-state metadata.

### Go state is intentionally different

`go.sum` is not modeled as a resolved build list. It may contain checksum entries for module versions that are not currently selected. UPM therefore tracks it for integrity while authoritative selected-module inventory and relationship information come from native Go graph queries.

This is a concrete example of the “leaky abstraction by design” principle: a common model must preserve ecosystem semantics instead of forcing false symmetry.

## Unified status

`upm status` composes the major read-only control-plane views without running every expensive check by default.

The default status includes:

- discovered components, ecosystems, and managers;
- direct/resolved dependency observation counts;
- structural `doctor` health;
- configured project-policy result;
- integrity-snapshot presence;
- non-mutating native-verifier coverage.

`--deep` explicitly opts into installed-environment traversal. `--storage` explicitly opts into filesystem measurement. Native verification commands themselves are not run merely to render status; status reports whether a safe verifier is configured for each component.

A project with structural doctor errors or configured policy violations returns a non-zero status code.

## Project and fleet policy

Policy is read-only enforcement stored in the existing `upm.toml` surface rather than another project format.

Current `[policy]` rules include:

- `require_lockfiles`: every discovered component must expose a native lock/checksum state file;
- `require_integrity_snapshot`: `.upm/state.json` must exist;
- `require_native_verification`: every component must have a configured non-mutating verifier;
- `allowed_managers` / `denied_managers`: constrain native manager ownership across ecosystems;
- `max_errors` / `max_warnings`: bound structural/deep doctor findings.

Invalid policy types and contradictory allow/deny sets are configuration errors. No policy configuration is permissive by default.

`upm policy` evaluates one project. `upm projects policy` evaluates each explicitly registered project independently; a missing root or invalid policy is reported for that project without preventing the remaining registry entries from being evaluated.

Policy affects diagnostics and exit status. It never edits manifests, lockfiles, toolchain declarations, or the registry in order to make a project pass.

## Manager ownership and ambiguity

UPM never guesses which native manager is authoritative when project state disagrees. Mutation/native-exec preflight blocks:

- malformed manifests;
- multiple manager-specific lock/state files that make ownership ambiguous;
- Node package-manager declaration vs lockfile mismatch;
- contradictory Node `packageManager` and `devEngines.packageManager` declarations;
- multiple Python manager configurations in one `pyproject.toml`;
- Python manager configuration vs lockfile mismatch;
- unknown/unsupported delegated managers;
- sync operations that require a native lockfile but have none.

A mixed repository also requires explicit component selection for single-component operations unless discovery finds exactly one component. `install --all` and `sync --all` validate every component before producing a batch.

## Manager-scoped native escape hatch

The common command vocabulary is intentionally incomplete. `upm exec` provides an escape hatch while retaining UPM’s component and manager-ownership safety model.

Planning selects one component and prefixes user-supplied manager arguments with that component’s authoritative manager. Execution:

1. resolves the manager executable explicitly;
2. builds an argv vector without invoking a shell;
3. runs in the selected component directory;
4. captures stdout/stderr and return code;
5. performs post-command doctor verification by default.

Execution remains preview-first and requires `--apply`. `pip` is represented as `python -m pip`; other currently configured managers use their native executable prefix.

This escape hatch does not attempt to classify arbitrary manager commands as safe or mutating. The safety guarantee is about manager/component ownership, shell avoidance, explicit preview/apply, and post-command observation—not about reinterpreting every native command’s semantics.

## Toolchain and package-manager version health

Presence alone is not enough: `doctor` compares active toolchain versions with component requirements when UPM can safely interpret the syntax.

Current compatibility evaluators cover:

- common Node semver comparator/caret/tilde/wildcard/OR patterns;
- common Python version specifiers;
- Rust bare minimum-version requirements;
- Go bare minimum-version requirements.

Unsupported syntax is an informational `toolchain.requirement-unverified` finding rather than a guessed result.

For Node projects, the same conservative rule is applied to declared npm/pnpm/Yarn/Bun versions. Exact manager declarations stay exact; explicit ranges stay ranges. Version commands use the executable path actually resolved for the manager/toolchain.

## Native state integrity

Where a native format is safely parseable with the standard library, adapters validate syntax during inspection:

- npm `package-lock.json` / `npm-shrinkwrap.json`: JSON;
- uv/Poetry/PDM lockfiles: TOML;
- `Cargo.lock`: TOML.

The npm adapter additionally compares root manifest dependency sections with v2/v3 package-lock root metadata and raises `lockfile.manifest-drift` when they disagree.

UPM does not heuristically parse opaque pnpm/Yarn/Bun internals simply to claim coverage.

## Non-mutating native verification

`upm verify` is a separate layer from structural parsing. A verifier is configured only when its command is intentionally non-mutating for the requested check.

Current plans include:

- npm: CI dry-run with scripts/audit/funding disabled;
- Bun: frozen dry-run with scripts disabled;
- uv: `uv lock --check`;
- PDM: `pdm lock --check`;
- Cargo: `cargo metadata --locked --no-deps --format-version 1`;
- Go: `go mod tidy -diff`.

Managers without a sufficiently safe verifier are reported as skipped. `--strict` can make a skip fail verification for callers that require complete coverage.

Structural `doctor` and native `verify` are deliberately distinct: one inspects what UPM can safely understand locally, the other asks authoritative native tools to validate semantics UPM should not reimplement.

## Package-cache integrity

Cache integrity is a separate concept from manifest/lock consistency and installed-environment drift.

The first authoritative cache-content verifier is Go. `upm verify --cache` uses Go’s own module verification command while copying project module state to a temporary adjacent modfile/sum pair. The real project `go.mod` and `go.sum` are isolated from writes and temporary files are removed after verification.

Coverage is intentionally narrow. Other ecosystems are skipped until UPM has an authoritative cache-content verification path with acceptable mutation and ownership semantics.

## Native dependency graph and impact

Flat resolved inventory is not enough for transitive reasoning. Native graph mode therefore asks authoritative ecosystem tooling for relationship information rather than fabricating edges from checksum/state files.

The implemented Go graph layer keeps these concepts distinct:

- selected module versions in the build list;
- requirement edges and the version requested by each edge;
- the selected version that wins after module version selection;
- replacements, including versioned and local replacements;
- main-module identity.

This supports native `graph`, `why`, `impact`, fleet impact, and native-enriched SBOM views without treating `go.sum` as a dependency graph.

## Resolved inventory and duplication

Resolved inventory is populated only where native state is a trustworthy concrete resolution source. Queries expose two separate concepts:

- **direct duplication**: repeated declarations/requirements in manifests;
- **resolved duplication**: repeated concrete versions/locations in supported native resolved state.

`duplicates --resolved` reports version divergence and physical npm lock locations where known. Duplication is informational: multiple versions may be required by incompatible constraints, platform conditions, or intentional isolation.

The registered-project layer exposes fleet resolved inventory and cross-project duplicates using the same normalized names. Native Go inventory can use the authoritative selected build list instead of checksum rows.

## Integrity snapshot

`.upm/state.json` is an observation snapshot, not a dependency lockfile. Version 1 stores:

- component identity, ecosystem, and manager;
- root-relative native manifest/state-file paths;
- file kind;
- SHA-256 digest;
- file size.

`doctor` compares current repository state against this baseline and reports changed, missing, untracked, invalid, or unsupported state. `snapshot` explicitly accepts a reviewed new baseline.

Machine-specific runtime versions are intentionally **not** embedded in this portable snapshot. Toolchain/manager version health is evaluated live instead, avoiding baseline churn between developers and machines.

## Deep installed-state checks

Normal `doctor` stays structural and relatively fast. `doctor --deep` opts into installed-environment traversal.

Current deep checks:

- npm v2/v3: compare lockfile physical package locations and versions with `node_modules/*/package.json`, including nested installs;
- local Python `.venv`: inspect `*.dist-info/METADATA` and compare installed Name/Version pairs with versions present in uv/Poetry/PDM resolved inventory.

Python deep checks intentionally do not classify every absent lockfile package as missing because lockfiles can contain optional/platform/group-specific resolutions. Avoiding false corruption reports is more important than forcing symmetry with npm.

## Repair boundary

`repair` starts from a deep doctor report and only considers installed-state finding codes. A finding is repairable only if its component can produce an existing safe native sync plan through the normal operation planner.

Examples include npm CI, pnpm frozen install, modern Yarn immutable install, uv locked sync, and Cargo locked fetch where applicable.

Structural corruption is not guessed away. Malformed manifests, lock/state conflicts, manager mismatches, and snapshot changes remain diagnosis-only until a repair can be defined without destroying user intent.

UPM does not promise transactional rollback after a native manager begins changing files.

## Package operations

Native operations stay manager-specific behind a common vocabulary.

Go demonstrates why the abstraction remains intentionally leaky:

- `add` -> `go get <module>`;
- `remove` -> `go get <module>@none`;
- `install`/`sync` -> `go mod download` (module-cache hydration);
- semantic consistency -> separate `verify` using `go mod tidy -diff`.

UPM does not claim these operations are identical to npm/uv/Cargo concepts; it gives them a predictable control-plane entry while retaining native semantics.

## Project tasks

Project workflows have two layers.

### Explicit UPM task DAGs

`upm.toml` task definitions use argv arrays, root-relative working directories, optional descriptions, and dependency edges. The planner rejects:

- shell command strings;
- working directories escaping the project root;
- unknown task dependencies;
- dependency cycles.

Execution is preview-first and stops on the first failed task.

### Native task fallback

When a requested task name is not explicitly defined in `upm.toml`, UPM can map supported native tasks:

- Node `package.json` scripts through the component's npm/pnpm/Yarn/Bun manager;
- Cargo `build`, `check`, `run`, `test`;
- Go `build ./...`, `test ./...`, `vet ./...`, and `run .`.

If multiple components expose the task, explicit component selection is required. Configured UPM tasks take precedence over native tasks with the same name.

## Initialization

`init` delegates to native generators rather than maintaining project templates. Current generic paths are:

- Node: npm, pnpm, Bun;
- Python: uv;
- Rust: Cargo;
- Go: `go mod init <module>`.

Initialization is preview-first and only accepts new/empty targets inside the selected root. Go requires an explicit module path. Adoption/force semantics remain separate future features.

## Local project registry

The default user-level registry is `~/.upm/projects.json`. It stores only roots explicitly registered by the user.

Capabilities include:

- idempotent add/remove/list;
- stale/missing-root handling;
- re-discovery and current health summaries;
- project/fleet policy evaluation;
- optional deep health;
- fleet resolved/native inventory and duplicate grouping;
- native fleet impact for supported ecosystems;
- fleet storage accounting.

There is intentionally no automatic home-directory crawler.

## Storage accounting

Storage analysis is measurement, not cleanup.

Current project-local artifact roots:

- Node `node_modules`;
- Python `.venv` and `__pypackages__`;
- Cargo `target`.

The scanner does not follow symlinks. Where inode information is available, hardlinked files are counted once. Fleet scans share inode identities across registered project roots so the same physical hardlinked bytes are not summed repeatedly.

The resulting byte count is **not** labeled reclaimable. Safe cache deletion, shared-store cleanup, and physical deduplication require ecosystem-specific ownership/provenance rules and remain future work.

## SBOM interoperability

The CycloneDX 1.7 exporter operates on concrete resolved inventory only.

- registry npm/PyPI/Cargo resolutions get Package URLs;
- repeated identical PURLs are deduplicated while occurrences are retained;
- Git/path/local resolutions receive deterministic UPM `bom-ref` identifiers without fabricated registry PURLs;
- direct requirements without a concrete resolved version are not converted into fake SBOM versions;
- native Go enrichment uses selected module versions/replacements rather than `go.sum` checksum rows.

SPDX remains a planned exporter rather than an alias for the CycloneDX data structure.

## Milestones

### M1 — Foundation — implemented

- Node/Python/Rust/Go adapters;
- recursive mixed-project discovery;
- normalized project graph;
- structured doctor findings;
- local-only validation scripts.

### M2 — Delegation — substantial first slice implemented

- native command planner/runner;
- preview-first install/add/remove/sync;
- explicit `--apply`;
- component selection;
- `install --all` / `sync --all`;
- post-operation verification;
- preview-first native initialization;
- preview-first manager-scoped native `exec` escape hatch.

### M3 — Integrity — substantial first slice implemented

- portable SHA-256 state snapshots;
- native syntax checks for parseable formats;
- npm manifest/lock drift checks;
- manager ownership/conflict preflight;
- toolchain version satisfaction;
- Node package-manager version drift;
- non-mutating native verification layer;
- Go authoritative package-cache content verification;
- opt-in npm/Python installed-state drift detection;
- preview-first safe repair plans.

Next integrity work:

- additional safe native/cache verification paths for opaque manager formats;
- richer Python environment-marker/group modeling;
- package/artifact provenance and checksum ownership across more ecosystems;
- explicit repair classes beyond environment resync.

### M4 — Cross-project intelligence — substantial first slice implemented

- direct/resolved/native `why`;
- direct/resolved duplicate classification;
- authoritative Go selected-module graph and impact;
- explicit local project registry;
- fleet health and policy summaries;
- public fleet inventory/duplicates/native impact;
- project/fleet storage accounting;
- CycloneDX export with native Go enrichment.

Next:

- authoritative transitive relationship ingestion for more ecosystems;
- global package/cache inventory with ownership/provenance;
- advisory/provenance integration;
- richer cross-ecosystem impact semantics;
- SPDX export.

### M5 — Project workflows and policy — first slice implemented

- safe `upm.toml` task DAGs;
- preview-first `tasks` / `run`;
- native Node/Cargo/Go task fallback;
- root-escape/cycle/shell-string guards;
- cross-ecosystem project policy;
- fleet policy evaluation;
- unified project `status`.

Next:

- richer task composition (explicit parallelism/resource semantics);
- environment/toolchain bootstrap integration;
- reusable/shared policy profiles without hiding local policy state;
- additional ecosystem-native tasks and adapters.
