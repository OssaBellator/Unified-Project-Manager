# Package-operation provider contract

UPM exposes a reusable package-operation planning contract for consumers that need ecosystem-specific native-manager argv without embedding UPM internals. The first contract is intentionally narrow: one discovered component and one of `install`, `sync`, `add`, or `remove` across the managers UPM already supports for delegated package operations: npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, and Go modules.

The planner is **read-only and networkless**. Planning performs static project discovery and reuses UPM's existing component/manager ownership and operation planning rules. Pure selection/argv logic lives in `package_planner.py`; the legacy `operations.py` execution adapter imports that planner rather than the public contract importing execution code. The provider never executes a manager, probes or installs a tool, writes project state, activates an environment, or accesses the network. Native managers remain authoritative for actual mutation and resolution.

## Public entrypoints

Python callers use `unified_project_manager.package_contract`:

```python
from unified_project_manager.package_contract import plan_package_operation

plan = plan_package_operation(
    "/workspace/project",
    "add",
    component="apps/web",
    packages=("react@19",),
    dev=True,
)
payload = plan.to_dict()
```

Structured embedding callers can use the JSON-compatible request function:

```python
from unified_project_manager.package_contract import plan_package_operation_json

payload = plan_package_operation_json({
    "requestSchemaVersion": 1,
    "projectRoot": "/workspace/project",
    "operation": "sync",
    "component": "apps/web",
    "packages": [],
    "dev": False,
})
```

Unknown request fields and incompatible request schema versions fail closed rather than being ignored.

CLI callers can use the normal UPM executable or the module entrypoint:

```text
upm package-plan sync --root /workspace/project --component apps/web --json
python -m unified_project_manager.package_contract_entrypoint sync --root /workspace/project --component apps/web --json
```

`--package` is repeatable for `add`/`remove`. `--dev` is only valid when the existing UPM operation planner permits it. `--json` emits the complete provider envelope suitable for another process.

## Versioned envelope

Provider and contract versions are deliberately outside the execution payload:

```json
{
  "schemaVersion": 1,
  "provider": {
    "name": "unified-project-manager.package-operation-planner",
    "version": "0.1.0"
  },
  "contract": {
    "name": "upm.package-operation-plan",
    "version": "1.0.0"
  },
  "ok": true,
  "compatibility": {
    "requestSchemaVersions": [1],
    "executionSchemaVersions": [1],
    "executionConstraintKinds": ["environment"],
    "planningEffects": {
      "managerExecution": false,
      "toolInstallation": false,
      "projectWrites": false,
      "networkAccess": false
    }
  },
  "workspaceScope": {
    "kind": "standalone",
    "rootComponent": null,
    "memberComponents": [],
    "issueCodes": []
  },
  "executionConstraints": {
    "environment": {}
  },
  "execution": {
    "schemaVersion": 1,
    "operation": "sync",
    "component": "apps/web:node",
    "ecosystem": "node",
    "manager": "npm",
    "cwd": "apps/web",
    "packages": [],
    "dev": false,
    "argv": ["npm", "ci"],
    "mutationScope": {"workspace": true, "external": false},
    "networkRequired": true
  }
}
```

`cwd` is always project-relative and POSIX-separated (`.` for the root). A plan whose working directory cannot be proven inside the selected project is rejected. `mutationScope.external` is therefore always `false` for a successful version-1 plan. Package inputs are limited to portable registry/module identifiers: manager options, control separators, local paths, URLs, VCS references/shorthands, and alias/source forms are rejected deterministically rather than being emitted as a supposedly workspace-only portable plan. Node slash syntax is limited to scoped package names; Go module paths remain valid.

`networkRequired` is conservatively `true` for every execution plan and means an executor must use its approved package-network lane if it executes the plan. A native manager might satisfy a particular invocation from local state, but a consumer must not infer execution networklessness from UPM's planning phase. Planning itself remains network-free.

`workspaceScope` records ownership evidence without broadening the execution payload. `standalone` means no static package-workspace owner claims the selected component. `workspace_root` means the selected component is the authoritative static root of a package.json, Cargo, or uv workspace; `rootComponent`, sorted `memberComponents`, and bounded `issueCodes` make that ownership visible to consumers. Version 1 deliberately refuses a selected workspace member with `workspace_member_requires_owner` rather than silently rewriting a component-scoped request into a broader root operation. A relevant pnpm workspace returns `workspace_inspection_required`: package.json or YAML files alone are not treated as proof of pnpm's authoritative member set, and the public planner never runs pnpm to resolve that ambiguity. Conflicting static ownership returns `workspace_ambiguous`.

Workspace pattern validation happens before globbing. Package.json, Cargo, and uv workspace patterns must be project-relative POSIX patterns and cannot use absolute/source paths, parent/dot segments, backslashes, symlink/reparse traversal, or matches that resolve outside the workspace root. This protects the planner's read boundary as well as its eventual mutation claim.

Yarn `sync` is accepted only when the manifest declares a parseable Yarn major version, so both component and package.json-workspace planning choose Classic `--frozen-lockfile` versus modern `--immutable` deterministically. Go `remove` accepts only unversioned module targets, and Go `add` rejects the removal sentinel `@none`. Pip version 1 is install-only and rejects requirement-file include/options, local paths, URL/VCS/direct-source forms, and continuations that could escape the portable project contract.

`executionConstraints` is beside, not inside, the schema-version-1 execution payload. Consumers must enforce every recognized constraint before executing that payload and fail closed on unknown constraint kinds. For Go module operations the provider emits `{"environment":{"GOWORK":"off"}}`, preserving UPM's existing component-scoped rule that ambient `go.work` state must not widen the selected module's execution scope. Other current managers emit an empty environment constraint. A consumer that cannot enforce the declared Go environment constraint must treat the Go plan as incompatible rather than execute only the schema-v1 payload.

## Stable failure boundary

Public failures raise `PackageContractError` with a stable bounded `code`, a message capped at 512 characters, and deterministic JSON-compatible `details` that never need absolute project paths. Machine callers should branch on the code rather than message text. Current version-1 codes include:

- `invalid_project_root`, `invalid_operation`, `invalid_component`, `invalid_packages`, `invalid_package`, `invalid_dev`, and `invalid_request` for malformed requests;
- `incompatible_request_schema` for unsupported structured requests;
- `no_component`, `component_ambiguous`, and `component_not_found` for selection failures;
- `manifest_invalid`, `manager_unknown`, `manager_ambiguous`, `manager_conflict`, `manager_unsupported`, `lock_required`, `packages_required`, `packages_forbidden`, and `dev_unsupported` for stable native-planning refusal classes;
- `operation_not_safe` for a conservative contract-specific refusal such as undeclared Yarn sync semantics or non-portable pip requirement directives;
- `workspace_member_requires_owner`, `workspace_inspection_required`, and `workspace_ambiguous` for package-workspace authority that v1 cannot safely narrow or prove statically;
- `manager_ecosystem_mismatch`, `external_read_scope`, `external_mutation_scope`, `discovery_failed`, and `planning_failed` for fail-closed integrity boundaries.

The serialized failure envelope has `schemaVersion: 1`, `ok: false`, and `error: {code, message, details}` and never includes `execution`. A success envelope has `ok: true` and never includes `error`. CLI planner failures return exit code `2`; with `--json`, failures retain provider/contract/compatibility metadata beside the structured error.

## Consumer security responsibilities

The provider contract is a planner, not an execution authorization. Consumers remain responsible for their own security boundary. In particular, consumers should:

1. pin and authenticate an exact UPM release/provider contract version before trust promotion;
2. reject unknown provider/contract/execution versions and unknown execution-constraint kinds rather than guessing compatibility;
3. enforce declared execution constraints, then independently validate operation, ecosystem/manager pairing, component identity, project-relative `cwd`, package grammar, exact argv semantics, mutation scope, and requested network policy;
4. enforce their own filesystem sandbox, permission model, `.git` protection, external-mutation denial, network allowlist/firewall, process isolation, and tool availability policy;
5. never install a missing manager or tool merely because a plan names it;
6. record execution and mutation evidence in the consumer's own journal/receipt boundary and recover unknown execution outcomes there;
7. treat native manager output and native manifests/locks as authoritative after execution and re-discover/revalidate state as required.

UPM does not claim that its planning metadata replaces those controls. The compatibility metadata states what the provider itself did during planning, not what an executor is allowed to do afterward.

## Versioning policy

`provider.version` is sourced from `unified_project_manager.__version__` and therefore identifies the actual UPM package/release that produced the plan. `contract.version` independently identifies the public envelope semantics. `execution.schemaVersion` is the narrow payload version intended for independently hardened executors.

A backward-compatible implementation fix can advance the provider version without changing the contract or execution schema. A change that adds/removes/renames public fields, changes their meaning, relaxes a fail-closed rule, or changes argv semantics in a way consumers must explicitly review requires an appropriate contract-version change. An execution-payload incompatibility requires a new execution schema version rather than silently changing schema version 1.

Consumers should promote exact releases only after their own contract fixtures and security revalidation pass. They should not vendor private UPM planner code or infer compatibility from the package's general version alone.

## Non-goals

This first contract does not execute managers, install tooling, perform workspace-wide batch planning, mutate Go workspaces, initialize projects, run arbitrary native `exec`, or replace UPM receipts/evidence with consumer journals. It does not broaden the ecosystem/manager set beyond UPM's existing delegated operation planner. Ambiguous ownership and any plan that cannot prove workspace-only mutation fail closed.

Version 1 may describe a statically proven package.json/Cargo/uv workspace root, but it does not turn an individual member request into a workspace-root mutation and it does not perform pnpm's native ownership inspection. Future owner-aware member or multi-plan batching belongs in a new reviewed contract capability rather than an implicit relaxation of this single-operation boundary.
