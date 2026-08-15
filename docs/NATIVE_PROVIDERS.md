# Native dependency provider contracts

UPM intentionally does not pretend every ecosystem exposes the same dependency graph. `--native` means “use the strongest authoritative relationship source UPM has configured for this ecosystem,” and every result carries a provider/scope label.

## Provider matrix

| Ecosystem | Provider | Evidence | Default network behavior | Mutation behavior |
| --- | --- | --- | --- | --- |
| Go | `go-modules` | selected module build list + module requirement graph | **offline/cache-only by default** (`GOPROXY=off`) | project `go.mod` / `go.sum` are read-only for graph queries |
| npm | `npm-lock-tree` | logical dependency tree reconstructed by npm from package-lock state | no package installation is required; provider uses `--package-lock-only` | none |
| pnpm | `pnpm-lock-tree` | logical dependency tree reconstructed by pnpm from `pnpm-lock.yaml`; native pnpm SBOM supplies package provenance | lockfile-backed inspection; no `node_modules` installation is required | none |
| Cargo | `cargo-metadata` | resolved package graph from Cargo metadata | **offline by default** (`--offline`) | lockfile is fixed by `--locked` |
| uv | `uv-lock` | static relationship graph from universal `uv.lock` | none | none |

The uv provider is publicly routed through graph/why/impact and native SBOM enrichment. It remains intentionally conservative around universal-lock forks.

## Go

UPM keeps three distinct Go concepts:

1. the selected module build list;
2. the module requirement graph (`go mod graph`);
3. package-import reasoning (`go mod why -m`).

They answer different questions. Module requirement reachability is not source/API/runtime reachability.

Public Go relationship queries execute through the offline provider wrapper. `GOPROXY=off` means missing cached module metadata is an explicit provider failure instead of a reason to contact a module proxy.

`go.work` is modeled as a first-class workspace. Component-scoped Go operations, tasks, initialization, native exec, and component verification disable ambient workspace inheritance with `GOWORK=off`. Explicit workspace commands instead pin the selected workspace file via `GOWORK=<absolute go.work>`.

Workspace-wide `go work sync` is preview-first and records before/after hashes for the workspace and member module files. External workspace members are blocked unless explicitly allowed.

## npm

The npm provider delegates logical-tree reconstruction to npm itself:

```text
npm ls --all --json --package-lock-only
```

This allows lock-only transitive inspection without requiring a physical `node_modules` installation.

Logical occurrence identity is preserved. If two ancestors resolve different copies of the same name/version, UPM does not collapse their paths for `why`/`impact` output.

For CycloneDX/SPDX enrichment, npm logical edges are attached only when the static package-lock inventory already established a trustworthy package identity/PURL. `npm ls` alone is not treated as proof of registry provenance.

## pnpm

pnpm has two complementary native sources.

Relationship queries use:

```text
pnpm list --depth Infinity --json --lockfile-only
```

In a workspace, UPM executes one recursive workspace-root query and preserves each returned project root. Logical occurrence identity retains:

- workspace project path;
- dependency alias versus actual package name (`from`);
- runtime/dev/optional/unsaved root scope;
- nested logical parent paths;
- pnpm's own `deduped` and `dedupedDependenciesCount` metadata.

A member selected with `--component` is promoted to its authoritative pnpm workspace root. Capability reporting uses the same ownership model, so a member without its own lockfile is still reported as covered when the root provider serves it.

Package provenance and SBOM relationships come from pnpm itself, not from heuristically interpreting `resolved` URLs:

```text
pnpm sbom --sbom-format cyclonedx --lockfile-only
pnpm sbom --sbom-format spdx --lockfile-only
```

For a whole workspace, UPM uses `--split` and ingests pnpm's NDJSON documents. For one selected member, UPM uses an exact root-relative `--filter` path. Native PURLs—including named-registry qualifiers emitted by current pnpm—are preserved when documents are merged into the cross-ecosystem BOM.

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

Conditional or ambiguous uv edges are not flattened into unconditional CycloneDX/SPDX relationships. Omission/ambiguity remains explicit evidence.

This is the intended general pattern for universal/multi-environment locks: uncertainty is data, not an invitation to pick the first candidate.

## `why` and `impact`

Provider scopes are deliberately different:

- Go `why`: `package-import-chain`;
- Go impact: `module-requirement`;
- npm: `logical-dependency-tree`;
- pnpm: `logical-dependency-tree` with workspace-project occurrence identity;
- Cargo: `locked-offline-dependency-graph`;
- uv: `universal-lock-dependency-graph`.

These scopes must remain visible in JSON and human output. None of them imply that vulnerable/changed source code is actually called at runtime.

## SBOM relationships

Package identity and relationship evidence remain provenance-aware.

- Go selected-module queries may add selected module identities and dependency edges.
- npm/Cargo providers add relationship edges only for endpoint identities already supported by static native state.
- pnpm uses pnpm's native lockfile-only CycloneDX/SPDX emitters as its package-identity authority; UPM remaps document-local refs while preserving native PURLs and registry qualifiers.
- uv relationships are admitted only when the universal-lock reference is unambiguous and unconditional for the target SBOM representation.
- local/path/workspace packages are never relabeled as registry packages solely to make a graph look complete.

## Failure policy

Native provider failure is explicit. UPM does not silently switch from:

- offline to online;
- locked to unlocked;
- workspace to component scope;
- authoritative native graph to a heuristic parser;
- ambiguous lock fork to an arbitrary candidate;
- native pnpm SBOM provenance to guessed tarball-origin identity.

A leaky but honest abstraction is preferred over false cross-ecosystem symmetry.
