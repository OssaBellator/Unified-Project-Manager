# uv workspace ownership

uv workspaces use shared project state. UPM must therefore model a member as part of one authoritative workspace instead of treating each `pyproject.toml` as an independent uv lock owner.

## Membership

Static membership comes from the workspace root's `[tool.uv.workspace]` table:

```toml
[tool.uv.workspace]
members = ["packages/*"]
exclude = ["packages/experimental"]
```

UPM expands these patterns only against Python components already discovered in the project graph. Excludes override member matches.

The workspace root itself remains part of the workspace model.

## Shared lock

A modeled uv workspace requires an authoritative `uv.lock` at the workspace root.

Members do not need their own lockfile and must not be reported as separate resolver owners merely because they contain `pyproject.toml`.

A selected member relationship query should promote to the root `uv.lock`. An excluded project with its own `uv.lock` remains a standalone uv graph owner.

## Nested workspaces

UPM currently fails closed when a member selected by one uv workspace is itself a uv workspace root. It does not flatten or guess nested ownership.

This keeps workspace ownership explicit until nested-workspace behavior can be represented with authoritative uv evidence.

## Batch operations

Workspace-owned install/bootstrap and locked sync collapse to one root command:

```text
uv sync --all-packages
uv sync --all-packages --locked
```

All proven workspace members are consumed by that root operation. Excluded/standalone Python components remain eligible for the ordinary component planner.

## Relationship planning

The additive workspace-aware uv relationship planner reads the shared root lock once. Member selection promotes to that plan rather than opening a nonexistent member lock.

The existing universal-lock parser keeps its previous safety behavior:

- markers are retained;
- forked/ambiguous references remain unresolved;
- reverse reachability never guesses through ambiguous edges.

## Local health

uv workspace health is filesystem-only and does not execute uv.

Current findings include:

- missing root `uv.lock` — error;
- nested workspace membership — error;
- overlapping workspace ownership — error;
- unmatched member patterns — warning.

These are intended to join the unified local status evidence once the aggregate workspace-health entrypoint is promoted to the extended Node/Cargo/uv aggregator.
