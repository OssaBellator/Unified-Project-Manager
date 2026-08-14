# Architecture

## Product boundary

UPM is a control plane over native package managers, runtimes, manifests, lockfiles, installed environments, and caches. It should not become a universal dependency resolver.

```text
CLI
  |
  +-- discovery ------> normalized ProjectGraph
  |                         |
  |                         +-- components
  |                         +-- managers
  |                         +-- manifests/lockfiles
  |                         +-- direct dependencies
  |                         +-- toolchain requirements
  |
  +-- graph queries ----> graph / why / duplicates
  |
  +-- doctor -----------> structural + integrity findings
  |
  +-- snapshot ---------> .upm/state.json checksums
  |
  +-- planner ----------> explicit native CommandPlan(s)
  |                         |
  |                         +-- preview by default
  |                         +-- refuse ambiguous state
  |
  +-- executor ---------> npm / pnpm / yarn / bun / uv / poetry / pdm / pip / cargo
                            |
                            +-- re-discover
                            +-- doctor verification
```

## Adapter contract

Ecosystem adapters own detection and inspection:

- `detect(directory)`: decide whether the directory is a project root for the ecosystem;
- `inspect(directory)`: translate native files into the normalized `Component` model.

Execution is deliberately separate from inspection. The operation planner converts a normalized component into an explicit native command, while the runner owns executable lookup, process execution, captured output, and post-operation verification. This prevents subprocess behavior from becoming entangled with manifest parsing.

## Normalized model

The model stores information that can be represented without pretending ecosystems are identical:

- ecosystem and component path/key;
- inferred native package manager and manager provenance;
- native manifest and lockfile names;
- runtime/toolchain requirement;
- normalized direct dependency name, native requirement text, and scope;
- adapter metadata and parse/read errors;
- structured doctor findings;
- explicit `CommandPlan` and `CommandResult` objects.

Native lockfiles remain the source of truth for exact resolution.

## Manager ownership and ambiguity

UPM must not guess which manager is authoritative when native project state disagrees. Current mutation preflight blocks:

- malformed manifests;
- multiple lockfiles for the same ecosystem component;
- Node `packageManager` vs lockfile mismatch;
- multiple Python manager configurations in one `pyproject.toml`;
- Python manager configuration vs lockfile mismatch;
- unknown/unsupported delegated managers;
- lock-required sync operations without a lockfile.

A mixed repository also requires explicit component selection for single-component operations unless there is exactly one component. `install --all` and `sync --all` validate every component before producing a batch; UPM does not silently omit components it cannot safely plan.

## Initialization

`upm init` delegates to native project generators rather than maintaining templates. The current native paths are:

- Node: npm, pnpm, Bun;
- Python: uv;
- Rust: Cargo.

Initialization is preview-first, requires `--apply` for execution, and currently accepts only new or empty targets inside the selected root. This conservative boundary prevents additive native init behavior from unexpectedly modifying an existing project. Adoption/force semantics should be designed separately rather than inferred.

## Integrity snapshot

`.upm/state.json` is a UPM observation snapshot, not a replacement dependency lockfile. Version 1 stores:

- normalized component identity, ecosystem, and manager;
- root-relative native manifest/lockfile paths;
- file kind;
- SHA-256 digest;
- file size.

`upm doctor` compares the current repository against the snapshot and reports changed, missing, untracked, invalid, or unsupported snapshot state. Snapshot changes are accepted explicitly with `upm snapshot`.

Future state versions can add environment fingerprints and native verification results without embedding a second dependency resolver.

## Doctor model

Health findings have a stable code, severity, optional component, message, and repair hint. Human and JSON output consume the same model.

Current checks include:

- malformed/unreadable native manifests;
- conflicting Node and Python lockfiles;
- manifest package-manager vs lockfile mismatch;
- multiple Python manager configurations;
- missing lockfiles where reproducibility is expected;
- unresolved package manager inference;
- manager/toolchain executable availability;
- repeated direct declarations inside a component;
- direct dependency requirement divergence across components;
- integrity snapshot changed/missing/new/corrupt state.

Informational dependency duplication/divergence does not lower the health score because duplication is not automatically an error.

Planned checks include:

- native lock/manifest verification without mutation;
- installed-state drift and undeclared packages;
- toolchain version satisfaction, not merely executable presence;
- cache integrity and artifact checksums;
- physical duplicate installations and reclaimable disk usage;
- package provenance, advisories, and SBOM export.

## Mutation safety

Every delegated mutation follows this shape:

1. discover all relevant components;
2. resolve the selected component(s) and native manager;
3. reject ambiguous or structurally unsafe manager state;
4. construct exact native `CommandPlan` objects;
5. show those plans without executing by default;
6. require explicit `--apply`;
7. invoke the native manager with an explicit working directory;
8. stop a multi-component batch on the first native failure;
9. re-discover the repository;
10. run doctor verification and surface structured results.

UPM does not roll back a package manager after it has started mutating files. Future repair/transaction work should use native snapshots and explicit recovery plans rather than pretending arbitrary ecosystem operations are atomically reversible.

## Query model

The current common dependency graph intentionally starts with direct declarations. It supports:

- `upm graph`: all normalized direct declarations;
- `upm why <name>`: components/scopes that directly declare a package;
- `upm duplicates`: repeated declarations and requirement divergence.

Python names are normalized for comparison across `-`, `_`, and `.` spelling variants. A later graph layer should ingest native lockfiles/SBOMs to answer transitive `why` and impact questions without parsing every resolver format in the first core model.

## Milestones

### M1 — Foundation — implemented

- Node/Python/Rust adapters;
- recursive mixed-project discovery;
- normalized project graph;
- structured doctor findings;
- local-only test/check scripts.

### M2 — Delegation — implemented first slice

- native command planner/runner;
- preview-first `install`, `add`, `remove`, and `sync`;
- explicit `--apply`;
- component selection;
- `install --all` / `sync --all`;
- post-operation discovery and doctor verification;
- preview-first native project initialization.

### M3 — Integrity — in progress

Implemented:

- portable manifest/lockfile SHA-256 snapshots;
- changed/missing/new snapshot findings;
- native manager ownership/conflict preflight;
- direct dependency duplication/divergence diagnostics.

Next:

- native frozen/locked verification as a read-only doctor mode;
- installed-state drift detection;
- runtime/toolchain version matching;
- cache/artifact integrity;
- repair plans that are previewed before execution.

### M4 — Cross-project intelligence — started

Implemented:

- direct cross-component `why`;
- duplicate declaration classification.

Next:

- transitive native dependency graph ingestion;
- machine-level project registry;
- physical duplicate/cache accounting;
- impact analysis;
- vulnerability/provenance integration;
- CycloneDX/SPDX export.

### M5 — Project workflows

- normalized task/run abstraction;
- project-level `dev`, `test`, and `build` orchestration;
- environment/toolchain bootstrap integration;
- optional machine-wide project health views.
