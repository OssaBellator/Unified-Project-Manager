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
 +-- doctor ---------------> structural / version / snapshot findings
 |                              +-- --deep installed-state findings
 |
 +-- native verifier ------> non-mutating manager/toolchain checks
 |
 +-- package planner ------> explicit native CommandPlan(s)
 |                              +-- preview by default
 |                              +-- refuse ambiguous ownership
 |
 +-- repair planner -------> safely mapped native sync plans only
 |
 +-- task planner ---------> upm.toml DAGs + supported native tasks
 |                              +-- argv only, no shell strings
 |                              +-- preview by default
 |
 +-- registry -------------> ~/.upm/projects.json
 |                              +-- fleet health / inventory / duplicates
 |                              +-- physical storage accounting
 |
 +-- snapshot -------------> .upm/state.json SHA-256 baseline
 |
 +-- exporters ------------> CycloneDX 1.7
```

The public `upm` console script and `python -m unified_project_manager` route through `entrypoint.py`. New workflow/storage surfaces live there while the existing package/health command implementation remains delegated to the established CLI module. This keeps compatibility while avoiding a single ever-growing parser module.

## Core model

The normalized model stores information only when it can be represented without pretending ecosystems are identical:

- ecosystem and component path/key;
- inferred native package manager and manager provenance;
- native manifest/state-file names;
- runtime/toolchain requirements;
- direct dependency name, native requirement text, and scope;
- concrete resolved package name/version/source/location when authoritative native state supports that observation;
- adapter metadata and parse/read errors;
- structured doctor findings;
- explicit command/task/verification plans and results.

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

`go.sum` is not modeled as a resolved build list. It may contain checksum entries for module versions that are not currently selected. UPM therefore tracks it for integrity/verification but leaves `ResolvedPackage` empty for the Go adapter until selected-module inventory is obtained from an authoritative native query.

This is a concrete example of the “leaky abstraction by design” principle: a common model must preserve ecosystem semantics instead of forcing false symmetry.

## Manager ownership and ambiguity

UPM never guesses which native manager is authoritative when project state disagrees. Mutation preflight blocks:

- malformed manifests;
- multiple manager-specific lock/state files that make ownership ambiguous;
- Node package-manager declaration vs lockfile mismatch;
- contradictory Node `packageManager` and `devEngines.packageManager` declarations;
- multiple Python manager configurations in one `pyproject.toml`;
- Python manager configuration vs lockfile mismatch;
- unknown/unsupported delegated managers;
- sync operations that require a native lockfile but have none.

A mixed repository also requires explicit component selection for single-component operations unless discovery finds exactly one component. `install --all` and `sync --all` validate every component before producing a batch.

## Toolchain and package-manager version health

Presence alone is not enough: `doctor` now compares active toolchain versions with component requirements when UPM can safely interpret the syntax.

Current compatibility evaluators cover:

- common Node semver comparator/caret/tilde/wildcard/OR patterns;
- common Python version specifiers;
- Rust bare minimum-version requirements;
- Go bare minimum-version requirements.

Unsupported syntax is an informational `toolchain.requirement-unverified` finding rather than a guessed result.

For Node projects, the same conservative rule is applied to declared npm/pnpm/Yarn/Bun versions. Exact manager declarations stay exact; explicit ranges stay ranges. Manager-version commands are cached per executable during one diagnosis.

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

Managers without a sufficiently safe documented verifier are reported as skipped. `--strict` can make a skip fail the verification command for callers that require complete coverage.

Structural `doctor` and native `verify` are deliberately distinct: one inspects what UPM can safely understand locally, the other asks authoritative native tools to validate semantics UPM should not reimplement.

## Resolved inventory and duplication

Resolved inventory is populated only where native state is a trustworthy concrete resolution source. Queries expose two separate concepts:

- **direct duplication**: repeated declarations/requirements in manifests;
- **resolved duplication**: repeated concrete versions/locations in supported native resolved state.

`duplicates --resolved` reports version divergence and physical npm lock locations where known. Duplication is informational: multiple versions may be required by incompatible constraints, platform conditions, or intentional isolation.

The registered-project layer exposes fleet resolved inventory and cross-project duplicates using the same normalized names. Go checksum entries are excluded because they are not selected module inventory.

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

Structural corruption is not guessed away. Malformed manifests, lockfile conflicts, manager mismatches, and snapshot changes remain diagnosis-only until a repair can be defined without destroying user intent.

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

Capabilities now include:

- idempotent add/remove/list;
- stale/missing-root handling;
- re-discovery and current health summaries;
- optional deep health;
- fleet resolved inventory and duplicate grouping;
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
- a Go Package URL mapping exists for future authoritative selected-module inventory, but `go.sum` checksum rows are not exported as resolved components.

SPDX remains a planned exporter rather than an alias for the CycloneDX data structure.

## Milestones

### M1 — Foundation — implemented

- Node/Python/Rust/Go adapters;
- recursive mixed-project discovery;
- normalized project graph;
- structured doctor findings;
- local-only validation scripts.

### M2 — Delegation — implemented first slice

- native command planner/runner;
- preview-first install/add/remove/sync;
- explicit `--apply`;
- component selection;
- `install --all` / `sync --all`;
- post-operation verification;
- preview-first native initialization.

### M3 — Integrity — substantial first slice implemented

- portable SHA-256 state snapshots;
- native syntax checks for parseable formats;
- npm manifest/lock drift checks;
- manager ownership/conflict preflight;
- toolchain version satisfaction;
- Node package-manager version drift;
- non-mutating native verification layer;
- opt-in npm/Python installed-state drift detection;
- preview-first safe repair plans.

Next integrity work:

- additional safe verification paths for opaque manager formats;
- richer Python environment-marker/group modeling;
- cache/artifact content integrity and provenance;
- explicit repair classes beyond environment resync.

### M4 — Cross-project intelligence — substantial first slice implemented

- direct/resolved `why`;
- direct/resolved duplicate classification;
- explicit local project registry;
- fleet health summaries;
- public fleet inventory/duplicates;
- project/fleet storage accounting;
- CycloneDX export.

Next:

- authoritative Go selected-module inventory via native graph queries;
- transitive relationship ingestion, not only flat resolved inventory;
- impact analysis;
- global package/cache inventory with ownership/provenance;
- advisory/provenance integration;
- SPDX export.

### M5 — Project workflows — first slice implemented

- safe `upm.toml` task DAGs;
- preview-first `tasks` / `run`;
- native Node/Cargo/Go task fallback;
- root-escape/cycle/shell-string guards.

Next:

- richer task composition (explicit parallelism/resource semantics);
- environment/toolchain bootstrap integration;
- additional ecosystem-native tasks;
- broader ecosystem adapters.
