# Native dependency provider contracts

UPM intentionally does not pretend every ecosystem exposes the same dependency graph. `--native` means “use the strongest authoritative relationship source UPM has configured for this ecosystem,” and every result carries a provider/scope label.

## Provider matrix

| Ecosystem | Provider | Evidence | Default network behavior | Mutation behavior |
| --- | --- | --- | --- | --- |
| Go | `go-modules` | selected module build list + module requirement graph | **offline/cache-only by default** (`GOPROXY=off`) | project `go.mod` / `go.sum` are read-only for graph queries |
| npm | `npm-lock-tree` | npm lock-only logical tree plus native lockfile-only SBOM provenance | lock-backed; no `node_modules` required | none |
| pnpm | `pnpm-lock-tree` | pnpm lock-only logical dependency tree plus native lockfile-only SBOM provenance | lock-backed; no `node_modules` required | none |
| Yarn Berry 2+ | `yarn-berry-resolution-graph` | exact descriptor/locator graph from native `yarn info` plus reachable-only SBOM identity | **offline by provider configuration** (`YARN_ENABLE_NETWORK=0`) | install state is redirected; cache is immutable |
| Cargo | `cargo-metadata` | resolved package graph from Cargo metadata | **offline by default** (`--offline`) | lockfile is fixed by `--locked` |
| uv | `uv-lock` | static universal project/workspace graph from authoritative shared `uv.lock` | none | none |

## Go

UPM keeps three distinct Go concepts:

1. the selected module build list;
2. the module requirement graph (`go mod graph`);
3. package-import reasoning (`go mod why -m`).

They answer different questions. Module requirement reachability is not source/API/runtime reachability.

Public Go relationship queries execute through the offline provider wrapper. `GOPROXY=off` means missing cached module metadata is an explicit provider failure instead of a reason to contact a module proxy.

`go.work` is modeled as a first-class workspace. Component-scoped Go operations, tasks, initialization, native exec, and component verification disable ambient workspace inheritance with `GOWORK=off`. Explicit workspace commands instead pin the selected workspace file via `GOWORK=<absolute go.work>`.

## npm

Relationship queries delegate lock-tree reconstruction to npm itself:

```text
npm ls --all --json --package-lock-only
```

No physical `node_modules` tree is required. Logical occurrence identity is preserved rather than collapsing repeated package versions onto one artificial node.

npm workspaces are root-owned for relationship evidence. An unscoped native graph queries the root lock once; selecting a member promotes the query to the root and adds an exact root-relative workspace selector such as:

```text
npm ls --all --json --package-lock-only --workspace ./packages/app
```

Package identity and SBOM relationships come from npm's native lockfile-backed SBOM instead of inferring provenance from `npm ls`:

```text
npm sbom --sbom-format cyclonedx --package-lock-only
npm sbom --sbom-format spdx --package-lock-only
```

Selected workspace SBOMs reuse the same exact path selector. npm may emit an older CycloneDX schema than UPM's aggregate; UPM imports compatible component/PURL/dependency assertions without downgrading the aggregate CycloneDX 1.7 document or copying native document UUID/timestamps.

## pnpm

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

A member selected with `--component` is promoted to its authoritative pnpm workspace root. Capability reporting uses the same ownership model.

Package provenance and SBOM relationships come from pnpm itself:

```text
pnpm sbom --sbom-format cyclonedx --lockfile-only
pnpm sbom --sbom-format spdx --lockfile-only
```

For a whole workspace, UPM uses `--split` and ingests pnpm's NDJSON documents. For one selected member, UPM uses an exact root-relative `--filter` path. Native PURLs—including named-registry qualifiers—are preserved when documents are merged into the cross-ecosystem BOM.

## Yarn Berry 2+

Relationship queries use Yarn's native stored-resolution surface:

```text
yarn info --all --recursive --virtuals --json
```

For an unscoped workspace query, UPM runs one root-owned `--all` query. Selecting a workspace member retains the authoritative root project while running the query from that member's cwd, so Berry applies the member's workspace context without inventing a second lock owner.

The provider preserves exact descriptors, locators, virtual package identity, devirtualized package relationships, and workspace locators instead of flattening them into name/version-only nodes. Yarn Classic is not claimed by this provider; the declared project manager and the resolved runtime must both be Yarn 2 or newer.

Execution is deliberately fail-closed and project-state-preserving:

- `YARN_ENABLE_NETWORK=0` refuses Berry network access;
- install state is redirected to a temporary path outside the project;
- `YARN_ENABLE_IMMUTABLE_CACHE=1` prevents supported cache mutation;
- telemetry is disabled;
- the provider does **not** force `YARN_ENABLE_HARDENED_MODE`, because hardened mode is not part of UPM's safety contract and forcing that optional setting can reject otherwise-supported older Berry runtimes;
- a runtime that cannot reconstruct the graph under these constraints fails explicitly rather than retrying online.

These are package-manager configuration guarantees, not an OS sandbox for arbitrary project-defined Yarn plugins. The fuller trust boundary is documented in `YARN_PROVIDER_TRUST_BOUNDARY.md`.

SBOM/advisory inventory is reachable-only: a locator returned by `yarn info --all --recursive` is not promoted merely because it exists in stored resolution data. UPM starts from active workspace/project roots and retains only reachable locators. npm-protocol resolutions can become npm PURLs where provenance is explicit; workspace, file, git, patch, and other non-registry resolutions remain non-registry identities.

## Cargo

The Cargo provider uses:

```text
cargo metadata --format-version 1 --locked --offline
```

`--locked` refuses lockfile drift; `--offline` refuses network access. Missing local registry/package metadata is an explicit provider failure.

Workspace ownership is not inferred from simple directory nesting. UPM builds a conservative static ownership model from Cargo manifests:

- when `[workspace].members` is present, those member paths/globs define the discovered member set, subject to `[workspace].exclude`;
- a root `[package]` is itself a workspace member;
- when a root package has **no explicit members list**, discovered in-root path dependencies are followed transitively as Cargo's automatic-membership fallback;
- `package.workspace` is treated as root/consistency evidence for already-proven membership, not as an independent membership grant.

Only manifests whose membership can be supported by that state are promoted to the workspace-root graph. An unrelated nested Cargo project with its own lockfile remains an independent graph owner. Unmatched explicit member patterns become local workspace-health warnings rather than silently claiming membership.

Cargo package IDs remain graph identity, so multiple versions of the same crate stay distinct. Dependency kinds and target expressions from Cargo metadata are retained on edges.

## uv

`uv.lock` is universal across environments, and a uv workspace has one shared authoritative lock. UPM therefore does not model workspace members as independent resolver states.

Workspace ownership is derived from `[tool.uv.workspace].members` and `exclude`. A workspace root without its shared `uv.lock`, overlapping ownership, or a nested included uv workspace fails closed. Stale/unmatched member patterns are surfaced by local workspace health.

Relationship planning follows shared-lock ownership:

- an unscoped query reads one `uv.lock` for the whole workspace;
- selecting a member promotes the read to the workspace-root lock while retaining the selected member's normalized project name/version as query context;
- selected `why`/`impact` only traverse packages reachable from that member's locked project node, so sibling-only paths do not leak into the answer;
- provider coverage uses the same ownership model, so members without a local lockfile are still correctly reported as served by `uv-lock`.

The static uv provider retains package/source identity and dependency markers. An edge resolves only when its lock reference identifies exactly one package. Ambiguous/forked references retain candidate IDs and are excluded from reverse reachability rather than guessed.

For native CycloneDX/SPDX export, `uv.lock` itself may establish PyPI identity for `source_kind = registry` packages. Local/editable/path/git/url packages are never relabeled as PyPI packages. A selected member exports only registry packages reachable from that member's project node; sibling-only packages are excluded. Marker-conditional or ambiguous edges are not flattened into unconditional SBOM relationships.

Workspace-wide install/sync planning is also root-owned. `install --all` collapses a proven uv workspace to one root `uv sync --all-packages`; reproducible `sync --all` adds `--locked` instead of independently syncing each member against a lock they do not own.

## Provider ownership and skips

Workspace-aware providers may serve more discovered components than the provider plan's root `component` field. UPM therefore derives provider coverage and skip suppression from provider plans:

- unscoped npm workspace root plans own all declared discovered members;
- scoped npm workspace plans own only root context plus the selected member;
- recursive pnpm plans own the pnpm workspace members they serve;
- unscoped Yarn Berry plans own the declared discovered workspace members they serve, while scoped plans retain root context plus the selected member;
- Cargo workspace plans own only manifest-proven members;
- unscoped uv workspace plans own all proven members, while scoped plans own only root context plus the selected member.

This prevents contradictory output where a workspace member is both successfully served by a root provider and reported as unsupported.

## `why` and `impact`

Provider scopes remain deliberately distinct:

- Go `why`: `package-import-chain`;
- Go impact: `module-requirement`;
- npm: `logical-dependency-tree`;
- pnpm: `logical-dependency-tree` with workspace-project occurrence identity;
- Yarn Berry: exact descriptor/locator resolution reachability with workspace/virtual identity;
- Cargo: `locked-offline-dependency-graph`;
- uv: `universal-lock-dependency-graph`, scoped to a selected workspace project when requested.

None implies source/API/runtime reachability or exploitability.

## SBOM relationships

Package identity and relationship evidence remain provenance-aware.

- Go selected-module queries may add selected module identities and edges.
- npm uses npm's native lockfile-only CycloneDX/SPDX package identity and relationships.
- pnpm uses pnpm's native lockfile-only CycloneDX/SPDX identity; UPM preserves native PURLs and registry qualifiers.
- Yarn Berry contributes only reachable stored resolutions; npm-protocol locators may become npm PURLs while workspace/file/git/patch/etc. remain non-registry.
- Cargo provider edges are admitted only where static lock provenance supports registry endpoint identity.
- uv may add registry package identities directly from authoritative `uv.lock`, but relationships are admitted only when the universal-lock reference is unambiguous and unconditional for the target representation.
- local/path/workspace packages are never relabeled as registry packages just to make a graph look complete.

## Failure policy

Native provider failure is explicit. UPM does not silently switch from offline to online, locked to unlocked, workspace to component scope, native evidence to heuristic parsing, an ambiguous lock fork to an arbitrary candidate, or native SBOM provenance to guessed download-origin identity.

A leaky but honest abstraction is preferred over false cross-ecosystem symmetry.
