# Architecture

## Product boundary

UPM is a control plane over native package managers, runtimes, manifests, lockfiles, installed environments, and local project inventory. It is deliberately **not** a universal dependency resolver.

```text
CLI
 |
 +-- discovery ------------> normalized ProjectGraph
 |                              |
 |                              +-- components / managers
 |                              +-- manifests / lockfiles
 |                              +-- direct dependencies
 |                              +-- resolved packages
 |                              +-- toolchain requirements
 |
 +-- graph queries --------> graph / why / duplicates
 |
 +-- doctor ---------------> structural + snapshot findings
 |                              +-- --deep installed-state findings
 |
 +-- snapshot -------------> .upm/state.json checksums
 |
 +-- planner --------------> explicit native CommandPlan(s)
 |                              +-- preview by default
 |                              +-- refuse ambiguous state
 |
 +-- repair planner -------> safe locked/frozen sync plans only
 |
 +-- executor -------------> npm / pnpm / yarn / bun / uv / poetry / pdm / pip / cargo
 |                              +-- re-discover
 |                              +-- doctor verification
 |
 +-- registry -------------> ~/.upm/projects.json
 |                              +-- explicit registered roots
 |                              +-- fleet health / resolved inventory
 |
 +-- exporters ------------> CycloneDX 1.7
```

## Core model

The normalized model stores only information that can be represented without pretending ecosystems are identical:

- ecosystem and component path/key;
- inferred native package manager and manager provenance;
- native manifest and lockfile names;
- runtime/toolchain requirements;
- direct dependency name, native requirement text, and scope;
- resolved package name/version/source/location parsed from supported native locks;
- adapter metadata and parse/read errors;
- structured doctor findings;
- explicit `CommandPlan` and `CommandResult` objects.

Native lockfiles remain the source of truth for exact resolution.

## Adapter boundary

Ecosystem adapters own detection and inspection:

- `detect(directory)`: decide whether a directory is a project root for the ecosystem;
- `inspect(directory)`: translate native files into a normalized `Component`.

Execution is separate. The operation planner converts a component into an explicit native command; the runner owns executable lookup, subprocess execution, captured output, and post-operation verification. This keeps resolver/CLI behavior out of parsers.

Current adapters:

- Node: `package.json`; npm/pnpm/Yarn/Bun manager ownership; npm v2/v3 lock inventory;
- Python: `pyproject.toml`, dependency groups, Poetry tables, requirements files; uv/Poetry/PDM TOML lock inventory;
- Rust: Cargo manifests/workspace dependencies and Cargo.lock inventory.

## Manager ownership and ambiguity

UPM never guesses which native manager is authoritative when project state disagrees. Mutation preflight blocks:

- malformed manifests;
- multiple manager-specific lockfiles for one component;
- Node package-manager declaration vs lockfile mismatch;
- contradictory Node `packageManager` and `devEngines.packageManager` declarations;
- multiple Python manager configurations in one `pyproject.toml`;
- Python manager configuration vs lockfile mismatch;
- unknown/unsupported delegated managers;
- sync operations that require a native lock but have none.

A mixed repository also requires explicit component selection for single-component operations unless discovery finds exactly one component. `install --all` and `sync --all` validate every component before producing a batch.

## Native lockfile integrity

Where the native format is safely parseable with the standard library, adapters validate syntax during inspection:

- npm `package-lock.json` / `npm-shrinkwrap.json`: JSON;
- uv/Poetry/PDM lockfiles: TOML;
- Cargo.lock: TOML.

The npm adapter additionally compares root manifest dependency sections with v2/v3 package-lock root metadata and raises `lockfile.manifest-drift` when they disagree.

UPM does not pretend to parse pnpm/Yarn/Bun formats without an appropriate parser/native verification path. Unsupported lock internals remain opaque rather than being heuristically interpreted.

## Resolved inventory and duplication

Parseable locks populate `ResolvedPackage(name, version, source, location)` records. Queries expose two separate concepts:

- **direct duplication**: repeated declarations/requirements in manifests;
- **resolved duplication**: repeated concrete package versions/locations in native locks.

`duplicates --resolved` reports version divergence and physical npm lock locations where known. Duplication is informational: two versions may be required by incompatible constraints, platform conditions, or intentional isolation.

The local registry also has a fleet aggregation primitive that can compare resolved package versions across explicitly registered project roots. A public fleet-duplicates CLI can build on that primitive without changing the core graph.

## Integrity snapshot

`.upm/state.json` is an observation snapshot, not a dependency lockfile. Version 1 stores:

- component identity, ecosystem, and manager;
- root-relative native manifest/lockfile paths;
- file kind;
- SHA-256 digest;
- file size.

`doctor` compares current repository state against this baseline and reports changed, missing, untracked, invalid, or unsupported state. `snapshot` explicitly accepts a reviewed new baseline.

## Deep installed-state checks

Normal `doctor` stays structural and fast. `doctor --deep` opts into installed-environment traversal.

Current deep checks:

- npm v2/v3: compare lockfile physical package locations and versions with `node_modules/*/package.json`, including nested installs;
- local Python `.venv`: inspect `*.dist-info/METADATA` and compare installed Name/Version pairs with versions present in uv/Poetry/PDM resolved inventory.

Python deep checks intentionally do not classify every absent lockfile package as missing because lockfiles can contain optional/platform/group-specific resolutions. Avoiding false corruption reports is more important than forcing symmetry with npm.

## Repair boundary

`repair` starts from a deep doctor report and only considers installed-state finding codes. A finding is repairable only if its component can produce an existing safe `sync` plan through the normal operation planner.

Current examples:

- npm installed drift -> `npm ci`;
- pnpm -> frozen install;
- modern Yarn -> immutable install;
- uv -> `uv sync --locked`;
- Cargo -> `cargo fetch --locked` where applicable.

Structural corruption is not guessed away. Malformed manifests, lockfile conflicts, manager mismatches, and snapshot changes remain diagnosis-only until a repair can be defined without destroying user intent.

UPM does not promise transactional rollback after a native manager begins changing files.

## Initialization

`init` delegates to native generators rather than maintaining project templates. The first supported generic paths are:

- Node: npm, pnpm, Bun;
- Python: uv;
- Rust: Cargo.

Initialization is preview-first and only accepts new/empty targets inside the current root. Adoption/force semantics should be separate explicit features.

## Local project registry

The default user-level registry is `~/.upm/projects.json`. It stores only roots explicitly registered by the user.

Capabilities:

- idempotent add/remove/list;
- stale/missing-root handling;
- re-discovery and current health summaries;
- optional deep health;
- fleet-level resolved-duplicate aggregation primitive.

There is intentionally no automatic home-directory crawler.

## SBOM interoperability

The first exporter emits deterministic CycloneDX 1.7 JSON from concrete resolved inventory.

- registry npm/PyPI/Cargo resolutions get Package URLs;
- repeated identical PURLs are deduplicated while occurrences are retained;
- Git/path/local resolutions receive deterministic UPM `bom-ref` identifiers without fabricated registry PURLs;
- direct requirements without a concrete resolved version are not converted into fake SBOM versions.

SPDX is a planned exporter, not an alias for the CycloneDX data structure. Its richer object/relationship model should be implemented explicitly.

## Milestones

### M1 — Foundation — implemented

- Node/Python/Rust adapters;
- recursive mixed-project discovery;
- normalized direct/resolved project graph;
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

- portable manifest/lockfile SHA-256 snapshots;
- native lockfile syntax checks for parseable formats;
- npm manifest/lock drift check;
- manager ownership/conflict preflight;
- opt-in npm/Python installed-state drift detection;
- preview-first safe repair plans.

Next integrity work:

- native manager verification modes for opaque lock formats;
- runtime/toolchain **version satisfaction**, not only executable presence;
- cache/artifact checksums and reclaimable storage accounting;
- richer Python installed-state/environment markers;
- explicit repair classes beyond environment resync.

### M4 — Cross-project intelligence — started

Implemented:

- direct/resolved `why`;
- direct/resolved duplicate classification;
- explicit local project registry;
- fleet health summaries;
- fleet resolved-duplicate aggregation primitive;
- CycloneDX export.

Next:

- public fleet duplicate/inventory commands;
- transitive relationship ingestion, not only resolved inventory;
- impact analysis;
- machine-wide disk/cache accounting;
- advisory/provenance integration;
- SPDX export.

### M5 — Project workflows

- normalized task/run abstraction;
- project-level dev/test/build orchestration;
- environment/toolchain bootstrap integration;
- broader ecosystem adapters.
