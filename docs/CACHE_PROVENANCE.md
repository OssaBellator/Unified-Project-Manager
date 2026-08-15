# Cache and package provenance

UPM treats **same package identity**, **same physical bytes**, and **safe to reclaim** as three different claims.

Physical cache provenance is read-only observation. It never creates a deletion target or upgrades unattributed bytes into unused bytes.

## Public cache provenance command

UPM exposes physical attribution for managers where native evidence can identify package source objects without reverse-engineering an opaque cache format:

```sh
upm cache provenance
upm cache provenance --manager go
upm cache provenance --manager cargo
upm cache provenance --registry ~/.upm/projects.json --json
upm cache provenance --closed-universe
```

The command considers only explicitly registered projects. It executes local/offline native relationship providers where physical identity is required:

- Go uses the routed offline module provider (`GOPROXY=off`);
- Cargo uses `cargo metadata --locked --offline`.

The command does not mutate projects or caches and does not invoke GitHub Actions.

Current physical attribution support is deliberately limited to **Go and Cargo**. npm, pnpm, and uv cache/store internals are not heuristically parsed merely to claim per-package physical provenance.

## Project-universe closure

By default, the registered project set is treated as an **open** universe: other projects or tools may use the same caches.

`--closed-universe` is an explicit user assertion that the registry is the complete relevant project set. It is not inferred. Missing or unreadable registered projects invalidate that assertion.

Project-universe closure and observation completeness are separate:

- `project_universe.closed` says whether the explicit closure assertion remains valid for the registered project list;
- `observation_complete` additionally requires usable cache roots, successful native providers, coverage of every applicable component, consistent physical identity, and internally consistent byte measurements.

A project universe may therefore be closed while the current cache observation is incomplete. Even a closed and completely observed registered universe does **not** make unattributed cache data reclaimable.

## Go physical module-cache provenance

Go attribution starts from the **native-reported physical module directory** for each selected module. UPM does not reconstruct Go's escaped module-cache path from a logical module name.

A selected module is source-cache-backed only when its native directory resolves underneath the measured `GOMODCACHE` root. Local replacements outside `GOMODCACHE` are excluded.

### Selected download-cache artifacts

When the native physical module directory has Go's canonical escaped `name@version` shape, UPM reuses that exact escaped physical path to look for the same selected version under:

```text
GOMODCACHE/cache/download/<escaped-module>/@v/
```

Only existing regular non-symlink `.info`, `.mod`, `.zip`, and `.ziphash` files are attributed. Lock/list metadata and files for other versions are not attributed to that selected occurrence.

If the native physical directory does not have canonical `name@version` form, UPM refuses to guess the download-cache layout.

Go build-cache bytes (`GOCACHE`) are measured by `upm cache storage` but remain outside selected-module package attribution.

## Cargo physical source provenance

Cargo attribution begins with `manifest_path` returned by `cargo metadata --locked --offline`, but the measured object is the enclosing **Cargo cache source object**, not necessarily the individual crate subdirectory containing that manifest.

Canonical physical objects are:

```text
CARGO_HOME/registry/src/<index>/<crate-version>
CARGO_HOME/git/checkouts/<repo>/<revision>
```

UPM derives those roots only from native-reported manifest locations already inside the corresponding Cargo source/check-out trees. Noncanonical shallow layouts fail closed.

This deliberately excludes:

- `registry/index`;
- `registry/cache` archive/metadata state;
- `git/db` repository database state;
- workspace/path dependencies outside `CARGO_HOME`;
- arbitrary directories merely located somewhere below `CARGO_HOME/registry` or `CARGO_HOME/git`.

### Registry source objects

An unpacked registry source object is expected to identify one registry package. Registry-source observations receive their Cargo PURL where provenance supports it.

If one physical registry source object is observed as multiple package identities, UPM reports an identity conflict and makes the observation incomplete rather than choosing one identity.

### Git checkout objects

A Cargo git checkout can legitimately contain a workspace with multiple crates. UPM therefore measures the checkout revision root **once** and records every package identity observed inside that checkout on the same physical group.

Multiple package identities inside one `git-checkout` group are not by themselves a conflict. They describe one shared physical source container. Git identities remain native Cargo package IDs rather than being relabeled as registry artifacts.

This avoids recursively assigning overlapping checkout bytes to each nested crate.

## Byte accounting and identity consistency

For each supported manager, the report separates:

- `total_bytes` — measured cache scope;
- `attributed_bytes` — physical source/download objects tied to native package observations from registered projects;
- `unattributed_bytes` — measured bytes not covered by those attributable objects;
- `coverage_ratio` — attributed divided by measured bytes where a non-zero total exists;
- `measurement_consistent` — false if attributed bytes exceed the measured cache total;
- `identity_consistent` — false when the physical object model yields contradictory identities;
- `identity_conflicts` — the conflicting path, observed identities, and reason.

Physical group measurement shares inode identity so hardlinked bytes are not double-counted where the filesystem exposes stable inode information.

Identity consistency is container-aware: legitimate multi-crate Cargo git checkouts may carry several identities, while conflicting Go path claims, multi-identity Cargo registry source objects, or incompatible groups for one physical path fail the consistency check.

The safety fields are unconditional:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

Unattributed bytes can include manager metadata, package objects outside current native physical evidence, projects not registered with UPM, tooling use, older versions, or other manager-owned state.

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
