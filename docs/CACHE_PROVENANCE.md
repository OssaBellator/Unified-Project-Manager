# Cache and package provenance

UPM treats “same package identity,” “same physical bytes,” and “safe to reclaim” as three different claims.

## Fleet package provenance

The fleet provenance index starts with concrete resolved package observations from explicitly queried/registered projects.

Where native provenance supports a registry Package URL, the PURL is the canonical logical identity. Non-registry Git/path/local artifacts keep deterministic UPM identities instead of being relabeled as registry packages.

The index can answer:

- which projects/components resolve an exact package identity/version;
- how many managers/components observe it;
- which native sources were recorded;
- where versions diverge across projects.

A package used by multiple projects is `shared_across_projects` logically. That does **not** establish shared or duplicated physical storage.

Every provenance group therefore states:

```text
physical_duplication_known = false
reclaimable = false
```

unless a future physical provider supplies stronger evidence.

## Go physical module-cache provenance

The first physical provider is Go because native Go module queries can expose the actual selected module directory.

UPM does **not** reconstruct `GOMODCACHE` escaped paths itself. A selected module is considered cache-backed only when:

1. the native graph exposes a concrete module directory;
2. that directory resolves underneath the queried `GOMODCACHE` root.

Versioned replacements use their native-reported replacement directory/identity. Local replacements outside GOMODCACHE are explicitly excluded from cache-backed attribution.

This allows multiple registered projects to be correlated to the same physical module directory without relying on cache filename conventions.

## Attribution coverage

For Go, UPM can compare:

- total physical GOMODCACHE bytes;
- physical bytes beneath module directories referenced by the native graphs that were actually inspected.

The remainder is called **unattributed bytes**.

Unattributed does not mean unused or reclaimable. It can include:

- download/cache metadata;
- modules used by projects not registered with UPM;
- modules used by tooling outside the registered project set;
- previously downloaded module versions;
- other manager-owned state.

Accordingly the attribution summary emits:

```text
unattributed_means_unused = false
reclaimable_bytes = null
```

It also carries provider failures and whether the queried project universe was considered closed.

## Cleanup boundary

UPM should continue preferring manager-defined prune/clean commands over direct deletion of cache paths.

Physical provenance can improve explanations and risk assessment, but it must not silently turn a directory observation into an `rm -rf` target.

A future per-package reclamation planner would need stronger ecosystem-specific ownership, liveness, concurrency, and cache-format guarantees than current provenance alone provides.
