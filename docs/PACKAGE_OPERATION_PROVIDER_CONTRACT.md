# Package-operation provider contract

UPM exposes a reusable dependency-operation planning contract for consumers that need native package-manager semantics without granting UPM execution authority. Planning is deterministic, project-read-only, networkless, and toolchain-independent. It never executes a package manager, probes or installs an SDK/toolchain, writes project state, changes the process environment, or accesses the network.

The current contract covers `install`, `sync`, `add`, and `remove` for npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, Go modules, and .NET/NuGet. Native manifests, lock/state files, package managers, and resolvers remain authoritative for the eventual mutation.

## Public entrypoints

Python callers use `unified_project_manager.package_contract`:

```python
from unified_project_manager.package_contract import plan_package_operation

plan = plan_package_operation(
    "/workspace/project",
    "add",
    component="src/App:dotnet",
    packages=("Newtonsoft.Json@13.0.3",),
)
payload = plan.to_dict()
```

Structured embedding callers use the JSON-compatible request function:

```python
from unified_project_manager.package_contract import plan_package_operation_json

payload = plan_package_operation_json({
    "requestSchemaVersion": 1,
    "projectRoot": "/workspace/project",
    "operation": "sync",
    "component": "src/App:dotnet",
    "packages": [],
    "dev": False,
})
```

Unknown request fields and incompatible request-schema versions fail closed. CLI callers can use:

```text
upm package-plan sync --root /workspace/project --component src/App:dotnet --json
python -m unified_project_manager.package_contract_entrypoint sync --root /workspace/project --component src/App:dotnet --json
```

`--package` is repeatable where the native operation supports package arguments. `--dev` is accepted only where the selected native manager has a safe corresponding development-dependency operation.

## Versioned execution contract

The current success envelope is schema version 2 and carries an execution schema version 2 payload. Request schema version 1 is retained because the request shape did not change. Contract version `2.0.0` marks the incompatible execution-payload extension: `executionConstraints` is now inside the execution object so an executor cannot detach the operation from constraints that are required for safe execution.

A representative payload is:

```json
{
  "schemaVersion": 2,
  "provider": {
    "name": "unified-project-manager.package-operation-planner",
    "version": "0.3.0"
  },
  "contract": {
    "name": "upm.package-operation-plan",
    "version": "2.0.0"
  },
  "compatibility": {
    "requestSchemaVersions": [1],
    "executionSchemaVersions": [2],
    "executionConstraintKinds": ["environment", "filesystem", "network", "prerequisites", "sources"],
    "planningEffects": {
      "managerExecution": false,
      "toolInstallation": false,
      "projectWrites": false,
      "networkAccess": false
    }
  },
  "ok": true,
  "workspaceScope": {
    "kind": "standalone",
    "rootComponent": null,
    "memberComponents": [],
    "issueCodes": []
  },
  "execution": {
    "schemaVersion": 2,
    "operation": "sync",
    "component": "src/App:dotnet",
    "ecosystem": "dotnet",
    "manager": "nuget",
    "cwd": "src/App",
    "packages": [],
    "dev": false,
    "argv": ["dotnet", "restore", "Fixture.csproj", "--locked-mode"],
    "mutationScope": {"workspace": true, "external": false},
    "networkRequired": true,
    "executionConstraints": {
      "environment": {},
      "filesystem": {
        "projectWrites": "workspace-only",
        "externalProjectWrites": false,
        "packageCache": "executor-isolated",
        "ambientProjectConfiguration": "isolated"
      },
      "network": {"required": true, "egress": "allowlisted"},
      "prerequisites": {
        "executables": ["dotnet"],
        "minimumVersions": {"dotnet": "10.0.0"},
        "provisioningAllowed": false
      },
      "sources": {
        "policy": "consumer-approved-registry-only",
        "allowCallerOverrides": false,
        "allowProjectOverrides": false,
        "allowAmbientOverrides": false,
        "allowLocalPaths": false,
        "allowUrls": false,
        "allowVcs": false
      }
    }
  }
}
```

`cwd` is always project-relative and POSIX-separated (`.` for the selected root). A plan whose working directory cannot be proven inside that root is rejected. `mutationScope.external` is therefore always `false` for a successful contract-v2 plan.

`networkRequired` remains the conservative compatibility signal that execution may need package-network access. The nested `network` constraint is the enforceable policy: an executor must use an allowlisted egress boundary rather than unrestricted networking. Planning itself remains network-free.

The `sources` constraint is generic and consumer-neutral. Contract v2 authorizes only consumer-approved registry sources and denies caller, project, and ambient source overrides, local paths, URLs, and VCS sources. Executors must fail closed if they cannot enforce those restrictions. The provider also rejects source-like package arguments itself; that does not replace executor revalidation.

The `filesystem` constraint separates project authority from package-cache mechanics. Native project writes must stay inside the selected workspace, external project writes are forbidden, package-cache activity must be redirected into an executor-isolated cache boundary, and ambient project configuration outside the selected workspace must be isolated. This is especially important for tools such as MSBuild/NuGet that otherwise search parent directories or user/machine state. These requirements are execution constraints; planning does not read parent/user configuration to make a plan succeed.

`prerequisites` describes what must already exist. `provisioningAllowed` is always `false`: a missing executable or unsupported version is prerequisite evidence, not permission to install an SDK, runtime, package manager, or image. For .NET/NuGet plans, the executable is `dotnet` with a minimum version of `10.0.0`, because the contract uses .NET 10 noun-first package commands. No tool presence/version probe occurs while planning.

The `environment` object contains exact required environment overrides. Go module operations preserve the existing component-isolation invariant with:

```json
{"GOWORK":"off"}
```

An executor that cannot set that exact value must reject the Go plan. Other current managers emit an empty required environment map.

Executors must reject unknown constraint kinds or unsupported constraint semantics rather than ignoring them.

## .NET and NuGet

UPM statically discovers `.csproj`, `.fsproj`, `.vbproj`, and classic `.sln` files. Project XML contributes target-framework, `PackageReference`, and `ProjectReference` observations without invoking MSBuild or `dotnet`. A solution is also represented as a .NET workspace observation.

Planning is intentionally narrow:

- project/solution install: `dotnet restore <target>`;
- project sync: `dotnet restore <target> --locked-mode`, requiring a native `packages.lock.json` (or project-specific `packages.<Project>.lock.json`); solution sync is refused until lock ownership across every member can be proven without widening authority;
- project add: one exact package per plan, expressed to UPM as `PackageId@Version`, rendered as `dotnet package add <PackageId> --version <Version> --project <project>`;
- project remove: one unversioned package id, rendered as `dotnet package remove <PackageId> --project <project>`.

Add/remove do not target solutions because solution-wide mutation would broaden authority across member projects. NuGet development-dependency scope is not invented; `dev=true` fails closed.

A directory containing multiple .NET project files, or multiple solution files without a unique project target, is ambiguous and cannot produce a package plan. Callers must select an unambiguous component rather than relying on filename guessing.

### .NET source and path containment

Contract-v2 .NET plans must remain portable across hardened executors. UPM therefore refuses selected projects whose effective in-root configuration attempts to choose package sources/cache roots itself. This includes:

- project properties such as `RestoreSources`, `RestoreAdditionalProjectSources`, `RestorePackagesPath`, or `NuGetPackageRoot`;
- those restore source/cache properties in applicable `Directory.Build.props`, `Directory.Build.targets`, or `Directory.Packages.props` files between the component and selected root;
- explicit MSBuild `<Import>` elements in the selected project or those ancestor build/package property files, because imported properties can alter restore semantics outside the statically proven contract;
- project-local `NuGet.Config` in that ancestor chain.

The contract does not serialize arbitrary `--source`, `--packages`, `--configfile`, restore-property, or caller-supplied manager flags. Source selection remains the executor's allowlisted policy responsibility.

`ProjectReference` and solution member paths must be literal project paths that resolve inside the selected root. Absolute paths, URLs, MSBuild property/item expansion, missing project files, or `..` traversal that escapes the root fail closed. Solution planning recursively validates every member project and its transitive `ProjectReference` graph before emitting restore argv, so an in-root `.sln` cannot hide an out-of-root project edge or member-level source override.

The selected project graph also rejects restore/output redirection properties such as `RestorePackagesPath`, `MSBuildProjectExtensionsPath`, `RestoreOutputPath`, and `ProjectAssetsFile`, plus explicit `Target`/`UsingTask` elements. Those constructs can redirect or execute restore-time behavior beyond what a static portable package-operation plan can prove. Common SDK-style implicit imports remain supported; arbitrary explicit imports do not.

## Portable package grammar

Package inputs are a conservative provider-owned subset, not arbitrary native-manager argv. Manager options, control separators, whitespace smuggling, local paths, URLs, VCS references, aliases/source forms, and other source-selection syntax are rejected deterministically.

Additional manager-specific rules remain in force. Examples include Go remove targets being unversioned, Go add rejecting `@none`, Yarn sync requiring a declared major so immutable/frozen behavior is deterministic, pip being requirements-file install-only in this contract, and NuGet add requiring an exact `PackageId@Version` while remove requires an unversioned id.

## Workspace ownership

`workspaceScope` records ownership evidence without silently widening authority. Static package.json, Cargo, and uv workspace roots may be represented as authoritative roots. Selected members fail with `workspace_member_requires_owner` instead of being rewritten to a broader mutation. pnpm ownership remains `workspace_inspection_required` when native read-only inspection would be needed; the public planner never runs pnpm to resolve that ambiguity.

.NET solution discovery is visible as a workspace observation, but contract-v2 add/remove remain project-scoped. A solution restore may reference only project files proven to remain inside the selected root.

Workspace pattern validation and existing ownership hardening remain shared UPM security primitives; the package contract does not bypass them.

## Stable failure boundary

Public failures raise `PackageContractError` with a stable bounded `code`, a message capped at 512 characters, and deterministic JSON-compatible details that avoid absolute host paths. Failure envelopes contain metadata plus `ok: false` and `error`, never `execution`.

Current failure classes include malformed requests/inputs, component selection ambiguity, manifest/manager/lock conflicts, unsupported manager semantics, unsafe package/source forms, workspace ownership ambiguity, and read/mutation scope escape. Consumers should branch on the code, not message wording.

## Consumer execution responsibilities

The provider plan is a narrow execution contract, not a substitute for an executor's security boundary. A conforming executor must independently:

1. authenticate/pin an accepted provider and contract version;
2. reject unknown envelope/execution versions and constraint kinds;
3. enforce every execution constraint before launching a native manager;
4. revalidate operation, ecosystem/manager pairing, component identity, root-relative `cwd`, package grammar, exact argv semantics, mutation scope, source policy, and network policy;
5. enforce workspace filesystem confinement, `.git` protection, process isolation, network allowlists, and consumer-controlled authority;
6. treat missing executables/toolchains as explicit prerequisite failure and never auto-provision them from a plan;
7. journal mutations and execution outcomes so timeout/unknown outcomes are recoverable without blind replay;
8. rediscover/revalidate native state after execution as needed.

UPM deliberately does not publish consumer-specific sandbox, image, host allowlist, permission, request-id, or write-session fields. Provider/consumer validation remains defense-in-depth rather than a shared bypass token.

## Versioning policy

`provider.version` comes from `unified_project_manager.__version__` and identifies the UPM release that emitted the plan. `contract.version` independently versions the public contract. `execution.schemaVersion` versions the narrow executor-facing payload.

The move from execution schema 1 to execution schema 2 is intentionally incompatible: required execution constraints moved into the execution object and expanded beyond environment-only metadata. Consumers that only accept execution schema 1 must reject schema 2 until they implement the new constraint model. Request schema 1 remains valid because no request-field semantics changed.

A compatible provider implementation fix can advance the provider release without changing the contract/execution schema. A public semantic or payload incompatibility requires a corresponding contract/execution version change rather than silently changing an existing schema.

## Non-goals

Planning does not execute managers, download packages, install toolchains, initialize projects, grant network access, or replace consumer mutation journals/recovery. It does not accept arbitrary native flags, arbitrary package sources, filesystem paths, or VCS dependencies. It does not turn a selected workspace member into broader workspace authority.

Execution readiness is achieved by making the safe native operation plus all required constraints explicit in the public payload; actual acquisition remains under a separately hardened, consumer-controlled executor.
