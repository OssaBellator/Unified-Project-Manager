# Project deduplication safety boundary

UPM distinguishes **duplicate observations** from **safe deduplication mutations**.

A package name appearing more than once does not imply that bytes can be deleted or that one version can replace another. Multiple versions may be required by incompatible constraints, isolated workspace/package-manager semantics, platform markers, major-version module paths, or different source identities.

## What UPM can safely mutate today

UPM only exposes a project-level dedupe mutation when the component's authoritative first-party manager defines one that UPM can delegate without inventing resolver semantics.

Current mutable dedupe capability is limited to:

- npm: `npm dedupe`;
- pnpm: `pnpm dedupe`;
- modern Yarn: `yarn dedupe`.

Yarn Classic is explicitly unsupported by this generic dedupe path. UPM does not substitute a third-party utility behind the user's back.

Bun, uv/Python, Cargo/Rust, and Go remain analysis/update/resolver workflows rather than receiving a fabricated `dedupe` mutation.

## Preview-first execution

Dedupe is preview-first. Preview reports:

- selected component/manager;
- exact native argv;
- manager-specific semantics;
- possible manifest/native-state/installed-state/network effects;
- mutation-receipt scope.

Applied dedupe delegates to the exact resolved manager executable and writes a v2 mutation receipt.

## Receipt limitation

Dedupe can rearrange an installed dependency tree without necessarily changing manifest/lockfile bytes.

UPM's mutation receipt is explicitly scoped to:

```text
project-native-state
```

It therefore records:

- the delegated dedupe command and return code;
- before/after manifest/native lock-state hashes;
- post-operation doctor verification when enabled.

It does **not** claim to be a byte-for-byte transaction log of every installed package directory. A successful dedupe may legitimately have all receipt file observations marked `unchanged` while the native manager has reduced the physical/logical installed tree.

Deep installed-state/storage analysis is a separate evidence layer.

## Failure behavior

A native dedupe command can fail after changing lock/native state. UPM rediscovers and writes the receipt even after non-zero return so partial native-state changes remain visible.

UPM does not automatically roll those changes back because restoring only manifests/locks could leave installed/cache state inconsistent with the manager's partial work.

## Duplicate categories

UPM's broader analysis should keep at least these concepts separate:

1. **Same logical identity observed more than once** — e.g. repeated occurrences in an npm tree.
2. **Multiple versions of one package/module name** — may be required or dedupe-compatible depending on native constraints.
3. **Different source/provenance identities with similar names** — not interchangeable.
4. **Physical duplicate bytes/directories** — a storage observation, not automatically safe to remove.
5. **Shared cache/store content** — often intentionally shared by many projects.
6. **Intentional environment/workspace isolation** — physical duplication may be the correct boundary.

A native dedupe command only addresses the subset that the native manager can prove/resolve according to its own rules.

## Cross-project duplicates

Registered-project duplicate reports remain observational. A package used in multiple repositories is not automatically reclaimable, even when the exact version matches.

Machine-wide physical provenance/cache accounting stays separate from project mutation.

## Non-goals

UPM dedupe does not:

- choose one universal version across ecosystems;
- delete cache/store entries merely because projects repeat a package;
- collapse Go major-version module paths;
- rewrite Cargo/Python dependency constraints to force one version;
- assume identical package names imply identical provenance;
- automatically clean installed trees based on storage estimates.

Native package managers and their resolvers remain authoritative for any actual dedupe mutation.