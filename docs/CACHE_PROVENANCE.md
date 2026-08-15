# Cache and package provenance

UPM treats **same package identity**, **same physical bytes**, and **safe to reclaim** as three different claims.

Physical cache provenance is read-only observation. It never creates a deletion target or upgrades unattributed bytes into unused bytes.

## Public cache provenance command

UPM exposes physical attribution for the managers where current native evidence can identify package source objects without reverse-engineering an opaque cache format:

```sh
upm cache provenance
upm cache provenance --manager go
upm cache provenance --manager cargo
upm cache provenance --registry ~/.upm/projects.json --json
```

The command considers only explicitly registered projects. It executes local/offline native relationship providers where physical identity is required:

- Go uses the routed offline module provider (`GOPROXY=off`);
- Cargo uses `cargo metadata --locked --offline`.

The command does not mutate projects or caches and does not invoke GitHub Actions.

Current physical attribution support is deliberately limited to **Go and Cargo**. npm, pnpm, and uv cache/store internals are not heuristically parsed merely to claim per-package physical provenance.

## Project-universe closure

By default, the registered project set is treated as an **open** universe: other projects or tools may use the same caches.

A user can explicitly assert that the registry is the complete relevant project set:

```sh
upm cache provenance --closed-universe
```

This is an assertion, not an inference. Missing or unreadable registered projects invalidate the closure assertion.

Project-universe closure and observation completeness are separate:

- `project_universe.closed` says whether the explicit closed-universe assertion remains valid for the registered project list;
- `observation_complete` additionally requires usable cache roots, successful native providers, no applicable provider coverage gaps, consistent physical identity, and internally consistent byte measurements.

Therefore a project universe may be closed while the current cache observation is incomplete because, for example, an offline native provider failed.

Even a closed and completely observed registered universe does **not** make unattributed cache data reclaimable. Package managers and tooling may own metadata or cache objects outside the package-source objects UPM can currently attribute.

## Go physical module-cache provenance

Go attribution starts from the **native-reported physical module directory** for each selected module. UPM does not reconstruct Go's escaped module-cache path from a logical module name.

A selected module is considered source-cache-backed only when its native directory resolves underneath the measured `GOMODCACHE` root. Local replacements outside `GOMODCACHE` are excluded.

### Selected download-cache artifacts

When the native physical module directory has Go's canonical escaped `name@version` shape, UPM reuses that exact escaped physical path to look for the same selected version under:

```text
GOMODCACHE/cache/download/<escaped-module>/@v/
```

Only existing regular non-symlink artifacts with these suffixes are attributed:

- `.info`;
- `.mod`;
- `.zip`;
- `.ziphash`.

UPM does not attribute lock/list metadata or files for other versions to that selected module occurrence.

If the native physical directory does not have the canonical `name@version` form, UPM refuses to guess the download-cache layout.

Go build-cache bytes (`GOCACHE`) are measured by `upm cache storage` but are intentionally outside selected-module package attribution.

## Cargo physical source provenance

Cargo attribution uses `manifest_path` returned by offline locked Cargo metadata.

A package source directory is cache-backed only when it resolves beneath one of these exact `CARGO_HOME` source roots:

```text
CARGO_HOME/registry/src
CARGO_HOME/git/checkouts
```

This deliberately excludes:

- `registry/index`;
- `registry/cache` archive/metadata state;
- `git/db` repository database state;
- workspace/path dependencies outside `CARGO_HOME`;
- arbitrary directories that merely happen to be somewhere below `CARGO_HOME/registry` or `CARGO_HOME/git`.

Registry-source packages receive their Cargo PURL when provenance supports it. Git checkout identity remains the native Cargo package ID rather than being relabeled as a registry artifact.

## Byte accounting and identity consistency

For each supported manager, the report separates:

- `total_bytes` — measured cache scope;
- `attributed_bytes` — physical source/download objects tied to native package observations from registered projects;
- `unattributed_bytes` — measured bytes not covered by those attributable objects;
- `coverage_ratio` — attributed divided by measured bytes where a non-zero total exists;
- `measurement_consistent` — false if attributed bytes somehow exceed the measured cache total;
- `identity_consistent` — false if one physical path is observed as more than one logical package identity;
- `identity_conflicts` — the conflicting path plus every identity observed for it.

Physical group measurement shares inode identity so hardlinked bytes are not double-counted where the filesystem exposes stable inode information.

Inode deduplication alone is not enough for provenance correctness. If two projects map the same physical path to different package identities, the bytes are still counted only once, but the report is marked incomplete and the conflicting identities are surfaced rather than silently choosing one.

The safety fields are unconditional:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

Unattributed bytes can include manager metadata, package objects not represented by current native physical evidence, projects not registered with UPM, tooling use, older versions, or other manager-owned state.

## Logical fleet package provenance

The separate logical provenance index starts with concrete resolved package observations from explicitly queried/registered projects.

Where native provenance supports a registry Package URL, the PURL is the canonical logical identity. Non-registry Git/path/local artifacts keep deterministic UPM identities instead of being relabeled as registry packages.

A package used by multiple projects is `shared_across_projects` logically. That does **not** establish shared or duplicated physical storage.

Logical provenance therefore keeps:

```text
physical_duplication_known = false
reclaimable = false
```

unless a physical provider supplies stronger evidence.

## Cleanup boundary

UPM continues to prefer manager-defined prune/clean commands over direct deletion of cache paths.

Physical provenance improves explanations and coverage accounting, but it is not a reclamation planner. A future per-package reclaim mechanism would need ecosystem-specific ownership, liveness, concurrency, cache-format, and manager-safety guarantees beyond the evidence currently collected.
