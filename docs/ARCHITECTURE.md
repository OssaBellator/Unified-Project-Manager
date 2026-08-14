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
  +-- doctor ---------> findings / health
  |
  +-- future mutation commands
          |
          +-- adapter -> native package manager
```

## Adapter contract

Each ecosystem adapter owns two responsibilities today:

- `detect(directory)`: decide whether the directory is a project root for the ecosystem;
- `inspect(directory)`: translate native files into the normalized `Component` model.

Mutation will be added behind explicit adapter methods only after read-only state is reliable. Likely future operations are `install`, `add`, `remove`, `sync`, `update`, `verify`, and `repair`.

## Normalized model

The initial model deliberately stores only information that can be represented without pretending ecosystems are identical:

- ecosystem and component path;
- inferred native package manager;
- native manifest and lockfile names;
- runtime/toolchain requirement;
- normalized direct dependency name, native requirement text, and scope;
- adapter metadata and parse errors.

Native lockfiles remain the source of truth for exact resolution.

## Doctor model

Health findings have a stable code, severity, optional component, message, and repair hint. That gives the CLI a human view while keeping JSON output machine-consumable.

Current checks:

- malformed native manifests;
- conflicting Node lockfiles;
- declared Node package manager vs lockfile mismatch;
- missing lockfiles where reproducibility is normally expected;
- unresolved package manager inference;
- manager/toolchain executable availability.

Planned checks:

- manifest/lock drift using native manager verification modes;
- installation drift and undeclared packages;
- version/toolchain mismatch, not merely executable presence;
- cache integrity and artifact checksums;
- duplicate logical and physical installations;
- package provenance, advisories, and SBOM export.

## Mutation safety

When mutation support lands, every operation should follow this shape:

1. discover the target component;
2. resolve the adapter and native manager;
3. snapshot relevant manifest/lock state;
4. invoke the native manager with an explicit working directory;
5. re-discover the component;
6. verify expected state changed and unrelated state did not;
7. surface a structured result.

This keeps UPM an orchestrator instead of a hidden second resolver.

## Near-term milestones

### M1 — Read-only foundation

- Node/Python/Rust adapters;
- project discovery;
- normalized project graph;
- doctor findings;
- local tests and checks.

### M2 — Delegation

- adapter command runner;
- `upm install`, `add`, `remove`, and `sync`;
- dry-run/command-preview mode;
- explicit component selection in mixed repositories.

### M3 — Integrity

- native frozen/locked verification;
- installed-state drift detection;
- environment and PATH checks;
- safe repair plans before execution.

### M4 — Cross-project intelligence

- machine-level project registry;
- duplicate/cache accounting;
- vulnerability/provenance integration;
- CycloneDX/SPDX export;
- cross-ecosystem `why` and impact analysis.
