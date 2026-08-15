# Cargo workspace ownership semantics

UPM must not infer Cargo workspace ownership from directory nesting alone. A nested `Cargo.toml` can be an independent project even when an ancestor contains `[workspace]`.

The relationship provider and local workspace-health layer therefore use a manifest-backed ownership model over **discovered Cargo manifests only**.

## Explicit `workspace.members`

When `[workspace].members` is explicitly present, UPM treats those paths/globs as the membership declaration, subject to `[workspace].exclude`.

A path dependency from an explicitly listed member to a sibling crate is **not** enough for UPM to add that sibling to workspace ownership. If the sibling has its own authoritative project state, it remains separate unless the workspace declaration includes it.

This matches Cargo's workspace-member discovery path: explicit member configuration is authoritative rather than a seed for arbitrary recursive directory ownership.

## No explicit members + root package

When the workspace root is also a package and no explicit `workspace.members` list is present, Cargo can discover workspace members through local path dependencies beneath the workspace root.

UPM mirrors that fallback over discovered manifests:

1. start with the root package;
2. follow local path dependencies within the workspace directory;
3. recurse through discovered path dependencies;
4. respect explicit workspace excludes;
5. never claim an undiscovered/non-manifest path as a component.

## `package.workspace`

A package-level `workspace` pointer identifies the workspace root the package expects. UPM uses it as a **consistency check for an already-proven member**.

It is not an independent membership grant and cannot override an explicit root `workspace.members` declaration.

If a manifest is included by the root workspace declaration but its `package.workspace` points somewhere else, UPM reports an ownership error and fails closed for workspace-owned native graph planning.

## Provider ownership

`cargo metadata --format-version 1 --locked --offline` runs once at each authoritative Cargo graph owner.

- a proven workspace member is served by its workspace root plan;
- an unrelated nested Cargo project with its own `Cargo.lock` remains an independent plan;
- selecting a proven member promotes to the root graph;
- selecting a non-member with its own lockfile keeps that component standalone.

Provider coverage and skip suppression use the same ownership model, so a component cannot be both root-served and reported unsupported.

## Local health

Cargo workspace health is evaluated without executing Cargo.

Current local findings include:

- unmatched explicit member patterns — warning;
- unreadable/invalid workspace manifests — error;
- contradictory workspace ownership or member root pointers — error.

These findings feed normal local `status` evidence. Native `cargo metadata` remains a separate explicit relationship-provider execution.
