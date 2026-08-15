# Native dependency provider contracts

UPM intentionally does not pretend every ecosystem exposes the same dependency graph. `--native` means “use the strongest authoritative relationship source UPM has configured for this ecosystem,” and every result carries a provider/scope label.

## Provider matrix

| Ecosystem | Provider | Evidence | Default network behavior | Mutation behavior |
| --- | --- | --- | --- | --- |
| Go | `go-modules` | selected module build list + module requirement graph | native Go may require cached/downloadable module metadata; offline hardening is tracked separately | project `go.mod` / `go.sum` are read-only for graph queries |
| npm | `npm-lock-tree` | logical dependency tree reconstructed by npm from package-lock state | no package installation is required; provider uses `--package-lock-only` | none |
| Cargo | `cargo-metadata` | resolved package graph from Cargo metadata | **offline by default** (`--offline`) | lockfile is fixed by `--locked` |
| uv | `uv-lock` | static relationship graph from universal `uv.lock` | none | none |

The uv provider is implemented as a static provider and is intentionally conservative around universal-lock forks. Public multi-provider routing can be enabled independently from the parser itself.

## Go

UPM keeps three distinct Go concepts:

1. the selected module build list;
2. the module requirement graph (`go mod graph`);
3. package-import reasoning (`go mod why -m`).

They answer different questions. Module requirement reachability is not source/API/runtime reachability.

`go.work` is modeled as a first-class workspace. Component-scoped Go operations, tasks, initialization, native exec, and component verification disable ambient workspace inheritance with `GOWORK=off`. Explicit workspace commands instead pin the selected workspace file via `GOWORK=<absolute go.work>`.

Workspace-wide `go work sync` is preview-first and records before/after hashes for the workspace and member module files. External workspace members are blocked unless explicitly allowed.

## npm

The npm provider delegates logical-tree reconstruction to npm itself:

```text
npm ls --all --json --package-lock-only
```

This allows lock-only transitive inspection without requiring a physical `node_modules` installation.

Logical occurrence identity is preserved. If two ancestors resolve different copies of the same name/version, UPM does not collapse their paths for `why`/`impact` output.

For CycloneDX enrichment, npm logical edges are attached only when the static package-lock inventory already established a trustworthy package identity/PURL. `npm ls` alone is not treated as proof of registry provenance.

## Cargo

The Cargo provider uses:

```text
cargo metadata --format-version 1 --locked --offline
```

This is deliberately stricter than normal Cargo metadata execution:

- `--locked` refuses lockfile drift;
- `--offline` refuses network access;
- missing local registry/package metadata is an explicit provider failure rather than a reason to silently go online.

Cargo package IDs are retained as graph identity so multiple versions of the same crate remain distinct.

A discovered Cargo workspace root owns nested member graph ingestion. Selecting a nested member is promoted to the authoritative workspace graph rather than executing duplicate workspace metadata queries.

Dependency kinds and target expressions from Cargo metadata are retained on edges.

## uv

`uv.lock` is a universal lockfile, so UPM does not reduce it to a single `{name -> version}` mapping.

The static uv provider:

- retains package name/version/source identity;
- marks local/editable/virtual/path packages as project members;
- retains dependency markers;
- resolves an edge only when a dependency reference identifies exactly one locked package;
- preserves all candidate package IDs when a name-only/forked reference is ambiguous;
- excludes ambiguous edges from reverse reachability paths rather than guessing.

This is the intended general pattern for universal/multi-environment locks: uncertainty is data, not an invitation to pick the first candidate.

## `why` and `impact`

Provider scopes are deliberately different:

- Go `why`: `package-import-chain`;
- Go impact: `module-requirement`;
- npm: `logical-dependency-tree`;
- Cargo: `locked-offline-dependency-graph`;
- uv: `universal-lock-dependency-graph`.

These scopes must remain visible in JSON and human output. None of them imply that vulnerable/changed source code is actually called at runtime.

## SBOM relationships

Static resolved inventory owns package identity. Native providers may enrich it with relationships only when identity/provenance is trustworthy.

- Go selected-module queries may add selected module identities and dependency edges.
- npm/Cargo providers add relationship edges only for endpoint identities already supported by static native state.
- local/path/workspace packages are never relabeled as registry packages solely to make a graph look complete.

## Failure policy

Native provider failure is explicit. UPM does not silently switch from:

- offline to online;
- locked to unlocked;
- workspace to component scope;
- authoritative native graph to a heuristic parser;
- ambiguous lock fork to an arbitrary candidate.

A leaky but honest abstraction is preferred over false cross-ecosystem symmetry.
