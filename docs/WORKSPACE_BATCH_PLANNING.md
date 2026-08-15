# Workspace-owned batch planning

A monorepo-wide operation cannot safely mean “run the package-manager command once in every discovered package directory.” Workspace roots often own dependency installation for their members.

UPM therefore models workspace ownership before a future all-component batch is executed.

## package.json workspaces

For npm/Yarn/Bun-style package.json workspaces, UPM can inspect membership statically:

- workspace patterns are expanded relative to the root;
- members are mapped back to discovered Node components;
- root/member manager mismatches fail planning;
- duplicate package names and stale/unmatched patterns are exposed by workspace health;
- nested package.json files outside the declaration are surfaced rather than silently included.

Workspace-owned commands currently modeled by the lower-level planner:

| Manager | install | reproducible sync |
| --- | --- | --- |
| npm | `npm install` | `npm ci` |
| Yarn | `yarn install` | `yarn install --immutable` |
| Bun | `bun install` | `bun install --frozen-lockfile` |

The planner returns both the root plan and the set of member component keys it consumes. Remaining components can then be handed to the normal per-component planner.

## pnpm

UPM intentionally does not implement a dependency-free YAML subset parser for `pnpm-workspace.yaml`.

Workspace ownership is established through pnpm itself:

```text
pnpm list -r --depth -1 --json
```

The inspection plan is read-only and uses the exact resolved pnpm executable.

Batch planning is two-stage:

1. explicitly inspect each pnpm workspace root;
2. pass the successful inspection result into the deterministic batch planner.

If a pnpm workspace is discovered but no inspection result is supplied, batch planning fails with `WorkspaceInspectionRequired` instead of treating every member as a standalone install target.

A failed inspection, member outside the project/workspace root, or conflicting member manager fails closed.

Modeled pnpm workspace commands:

- install: `pnpm install`;
- sync: `pnpm install --frozen-lockfile`.

Frozen sync requires a workspace-root `pnpm-lock.yaml`.

## Why inspection is not implicit in the pure planner

Planning should remain deterministic and side-effect transparent. A function that merely receives a project graph should not unexpectedly spawn package-manager processes.

Native inspection is therefore a separate explicit capability. Higher-level CLI code can choose to preview/execute that read-only inspection before constructing the final mutation plan.

## Operation safety

Workspace collapse changes *where* a native command should execute; it does not weaken UPM's mutation rules.

A final public all-component execution path should still:

1. resolve all workspace ownership first;
2. fail the entire preflight if any ownership is ambiguous;
3. preview every root + standalone native command;
4. require explicit apply;
5. stop execution after the first native failure;
6. re-discover/verify state;
7. record mutation receipts.

This prevents both redundant installs and partial planning that silently ignores an ambiguous workspace.
