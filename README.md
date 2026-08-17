# Unified Project Manager

Unified Project Manager (`upm`) is an experimental **local-first control plane over native project and package managers**.

UPM does not replace npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, Go modules, or their native resolvers. Native manifests, lock/state files, tools, caches, and resolution semantics remain authoritative. UPM coordinates those systems through one project model for discovery, health, policy, preview-first mutation, dependency relationships, workspaces, security evidence, storage, and machine-wide project correlation.

The implementation targets Python 3.11+ and has no runtime dependency outside the standard library.

**No GitHub Actions workflows are used.** Validation is local and script-driven.

## Ecosystem coverage

| Ecosystem | Native managers/tooling | Current control-plane coverage |
| --- | --- | --- |
| Node | npm, pnpm, Yarn, Bun | discovery, ownership, workspaces, direct/resolved inventory, package scripts, operations, native verification, npm/pnpm/Yarn Berry relationship graphs, cache/store coverage |
| Python | uv, Poetry, PDM, pip | PEP 621/dependency groups/Poetry/requirements discovery, resolved lock inventory, operations, native verification, installed `.venv` checks, conservative uv universal-lock plus validated Poetry/PDM structured-lock graphs |
| Rust | Cargo | package/workspace discovery, `Cargo.lock` inventory, operations/tasks, locked offline metadata graph, native verification, storage/provenance |
| Go | Go modules/workspaces | `go.mod` + `go.work`, checksum/workspace state, offline selected-module graph, replacements, impact/why, cache verification, provenance, tasks, operations/workspace sync |

Across those ecosystems UPM provides:

- recursive mixed-repository discovery;
- normalized components, workspace manifests, manager ownership, direct dependencies, resolved inventory, and toolchain requirements;
- structural `doctor` findings, workspace health, portable integrity snapshots, and composed `status`;
- preview-first native mutation with automatically persisted mutation receipts;
- optional deterministic receipt-chain anchoring for local tamper evidence;
- native semantic verification and ecosystem-specific cache/store checks;
- direct, resolved, and authoritative native graph/why/impact views;
- project policy and registered-project fleet policy/impact/status/storage views;
- CycloneDX 1.7 and SPDX 2.3 JSON SBOM export;
- preview-first OSV-Scanner advisory scanning with persisted project/fleet evidence;
- machine-wide cache/storage observation and explicit native cache maintenance;
- JSON output for automation without requiring a hosted control plane.

## Local validation

Run the aggregate local suite:

```sh
sh ./scripts/check-all-local-latest.sh
```

That layers the baseline compile/unit suite with integration/provider, native-security, Yarn Berry, and validated Poetry/PDM provider slices.

The baseline repository check remains independently runnable:

```sh
sh ./scripts/check.sh
```

`check.sh` runs Python `compileall` and the standard-library `unittest` suite.

A smaller cross-cutting integration slice is also available:

```sh
sh ./scripts/test-integration.sh
```

Focused provider/security drivers include:

```sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
```

Run UPM without installation:

```sh
PYTHONPATH=src python3 -m unified_project_manager status .
```

Or install into an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
upm status .
```

## Unified status and persisted evidence

`status` is intentionally local and cheap:

```sh
upm status .
upm status . --json
upm status . --deep
upm status . --storage
```

It composes already-available evidence rather than silently running scanners or native relationship queries. Current status includes:

- discovered components, workspaces, ecosystems, and managers;
- direct/resolved dependency counts;
- structural doctor health and workspace health;
- project policy result;
- `.upm/state.json` integrity-snapshot presence;
- native verifier and cache-integrity coverage;
- authoritative relationship-provider coverage;
- persisted advisory-evidence state;
- latest mutation-receipt state/drift;
- optional receipt-chain validation when `.upm/receipt-chain.json` exists;
- optional installed-state checks with `--deep`;
- optional local artifact measurement with `--storage`.

Current blockers include doctor errors, workspace errors, policy violations, current known vulnerabilities, invalid/drifted receipt state, and a broken receipt chain when one has been explicitly anchored. Missing optional advisory, mutation-receipt, or receipt-chain evidence is reported but is not itself a blocker unless policy requires the corresponding evidence.

`status` does **not** run OSV-Scanner, native graph providers, cache maintenance, or filesystem storage traversal unless the explicitly documented status option asks for that local traversal.

## Project health and integrity snapshots

```sh
upm discover .
upm doctor .
upm doctor . --deep
upm snapshot .
```

`doctor` checks structural state, manager ownership, lock/state conflicts, parse errors, tool availability, toolchain/version drift, integrity snapshots, and other cross-ecosystem findings.

`doctor --deep` additionally inspects installed environments where UPM has a sufficiently reliable mapping today, including npm `node_modules` and local Python `.venv` metadata.

`snapshot` writes `.upm/state.json` with root-relative native state paths, sizes, component/workspace identity, and SHA-256 hashes. It is an observation baseline, **not** a replacement dependency lockfile.

## Preview-first mutations and mutation receipts

Package operations remain preview-first:

```sh
upm add react --component frontend
upm sync --component backend
upm install --all
```

Execution requires `--apply`:

```sh
upm add react --component frontend --apply
upm sync --component backend --apply
upm sync --all --apply
```

Applied package operations automatically persist a receipt under `.upm/receipts/`. A receipt records redacted argv, native return codes, before/after native state hashes, normalized dependency deltas, and post-operation verification when enabled. Failed native commands still produce a receipt containing any partial manifest/lock-state changes that occurred before failure.

The same receipt model is used for applied:

- package `install`, `sync`, `add`, and `remove`;
- workspace-aware `install --all` and `sync --all`;
- in-root `go work sync`;
- `repair`;
- native-manager `exec`;
- `init`.

Sensitive command arguments are redacted before persistence. Preview-only commands do not create mutation receipts.

Inspect the receipt history and current native-state drift locally:

```sh
upm receipts .
upm receipts . --json
```

The command is read-only and network-free. It returns non-zero when stored receipts are invalid or the current native project state differs from the latest receipt baseline.

### Optional receipt hash chain

UPM can build a deterministic local chain over the current receipt set:

```sh
upm receipts chain .
upm receipts chain . --apply
```

The command is preview-first. `--apply` writes `.upm/receipt-chain.json` and exposes a deterministic anchor digest. Once a chain exists, later receipt additions/removals/changes make the old chain invalid until the user explicitly re-anchors it.

The chain is **tamper-evident but not externally authenticated**. UPM does not claim the local chain proves authenticity against an attacker who can rewrite both the receipts and the chain manifest; the anchor digest is provided so a separate trust system can record it if desired.

UPM refuses mutation when manager/component/workspace ownership is ambiguous rather than choosing a plausible command and hoping it is correct.

### Reusable package-operation planner contract

Consumers that need UPM's native manager selection/argv semantics without giving UPM execution authority can use the versioned, read-only provider contract:

```sh
upm package-plan sync --root . --component frontend --json
```

The planner returns provider/contract compatibility metadata beside a Windows-Tester-compatible `schemaVersion: 1` execution payload. Planning is deterministic, networkless, and project-read-only: it never executes managers, installs tools, or writes project state. Ambiguous ownership and any working directory outside the selected project fail closed. Hardened consumers remain responsible for independently revalidating plans and enforcing their own permission, sandbox, network, mutation-journal, and recovery boundaries.

See [`docs/PACKAGE_OPERATION_PROVIDER_CONTRACT.md`](docs/PACKAGE_OPERATION_PROVIDER_CONTRACT.md) for the Python/JSON/CLI API, schema, security responsibilities, and versioning rules.

## Workspace-aware batch operations

For Node workspaces, `install --all` and `sync --all` avoid double-running every member as an independent project.

Package.json-defined npm/Yarn/Bun workspaces are modeled statically. pnpm workspace ownership is confirmed through a non-mutating, no-network native inspection before planning. Workspace-owned components collapse to one authoritative workspace-root command; unrelated components in the same repository remain standalone batch steps.

For example, an npm workspace plus a Cargo project can produce one npm workspace command and one Cargo command instead of one npm command per package.

External workspace members or unresolved ownership fail closed.

## Go workspaces

UPM models `go.work` and `go.work.sum` as first-class workspace state.

```sh
upm workspaces .
upm workspace inspect .
upm workspace inspect . --preview
upm workspace graph .
upm workspace impact example.com/module .
upm workspace sync .
upm workspace sync . --apply
```

Static discovery can report workspace presence without Go installed. Authoritative membership/replacement inspection delegates to `go work edit -json`.

`go work sync` is preview-first. UPM preflights workspace members and refuses external-member mutation unless explicitly allowed because native workspace synchronization can update member `go.mod` files.

An internal-only applied workspace sync writes a complete project mutation receipt, including partial state after native failure. If `--allow-external` permits member modules outside the selected project root, UPM intentionally **does not** write a project receipt: doing so would falsely imply that out-of-root mutations were fully captured. The command instead reports `receipt_scope=external-unrepresented` and preserves the native changed-file report.

Component-scoped Go package operations/tasks/exec disable ambient workspace inheritance with `GOWORK=off`; explicit workspace commands instead bind to the discovered workspace.

## Authoritative dependency relationship providers

UPM does not force all ecosystems into one graph meaning. Each provider declares its evidence and scope.

### Go: selected modules, offline by default

```sh
upm graph . --native
upm why example.com/module . --native
upm impact example.com/module . --native
```

Go relationship execution uses the native selected build list and requirement graph with `GOPROXY=off`. Missing local module data therefore fails explicitly instead of silently fetching from a module proxy.

UPM keeps distinct:

- selected module versions;
- versions requested by individual requirement edges;
- versioned/local replacements;
- package-import reasoning from `go mod why -m`;
- module requirement impact.

Go impact is module-requirement impact, not source/API/symbol/runtime-call impact.

### npm: logical lock-tree relationships

For npm-owned projects with `package-lock.json`/`npm-shrinkwrap.json`, native graph mode delegates to:

```text
npm ls --all --json --package-lock-only
```

Logical occurrence identity is preserved, so two copies of the same package/version below different parents are not silently collapsed into one occurrence. npm impact/why therefore reports logical dependency paths.

### pnpm: workspace-aware logical lock-tree relationships

pnpm native relationship queries use:

```text
pnpm list --depth Infinity --json --lockfile-only
```

Workspace queries preserve project roots, aliases, dependency scope, parent paths, and pnpm dedupe metadata. Fleet native inventory carries that same logical occurrence context instead of flattening every pnpm observation to name/version only.

### Yarn Berry 2+: isolated stored-resolution relationships

Yarn Berry native graph mode uses `yarn info --all --recursive --virtuals --json` with Berry network access disabled, install state redirected outside the project, telemetry disabled, and immutable cache behavior. Exact locators, descriptors, virtual packages, and workspace identity are retained.

Stored Yarn records are not automatically active dependencies: SBOM/advisory/fleet inventory is limited to locators reachable from active workspace/project roots. Yarn Classic is not claimed by this provider.

### Cargo: locked offline metadata graph

Cargo native relationships use:

```text
cargo metadata --format-version 1 --locked --offline
```

The provider preserves package IDs, multiple crate versions, workspace membership, dependency kinds, and target information. It never goes online to make a graph query succeed.

### uv: conservative universal-lock graph

uv relationship analysis reads `uv.lock` directly and performs no subprocess or network operation.

`uv.lock` may contain conditional/forked universal resolution state. UPM preserves dependency markers and only declares an edge resolved when the lock reference identifies exactly one package. Ambiguous references remain explicit and are not guessed.

```sh
upm graph . --native --component backend
upm why some-package . --native --component backend
upm impact some-package . --native --component backend
```

### Poetry and PDM: validated structured-lock graphs

Poetry/PDM relationship analysis reads `poetry.lock` / `pdm.lock` statically with no manager subprocess, environment activation, network access, or project mutation.

Both use `structured-lock-dependency-graph` scope. Exact-one-candidate references become resolved edges; duplicate-name candidates remain explicit ambiguity; missing candidates remain unresolved. Marker/optional conditions are preserved rather than flattened.

Public `why`, project/fleet impact, SBOM, advisory correlation, and fleet inventory share the same certainty model:

- resolved `unconditional` / `conditional` paths;
- ambiguity-derived `possible` paths containing explicit `?dependency` hops;
- possible state propagating through descendants of every ambiguous candidate;
- bounded path/search traversal with visible truncation rather than silent path loss.

Unsupported structured-lock semantics fail closed instead of falling back to environment-dependent Poetry/PDM commands.

## Native semantic verification

Structural parsing and authoritative semantic verification remain separate:

```sh
upm verify .
upm verify . --preview
```

Configured checks include npm CI dry-run, Bun frozen dry-run, `uv lock --check`, `pdm lock --check`, locked Cargo metadata, and `go mod tidy -diff`.

Unsupported managers are skipped rather than probed with an unclassified command.

## Security advisory scanning

UPM can scan a temporary CycloneDX SBOM with OSV-Scanner when it is installed:

```sh
upm audit .
upm audit . --apply
upm audit . --apply --json
upm audit . --native --apply
upm audit . --native-go --apply
```

Audit is preview-first because OSV-Scanner may use the network. `--native` builds one provider-backed inventory before scanning; the provider inventory itself follows each provider's local/offline contract. `--native-go` remains a compatibility mode that enriches only through the offline Go provider.

A valid applied scan persists `.upm/audits/osv.json`, including the canonical SHA-256 of the exact SBOM that was scanned. Static-inventory evidence can therefore be classified locally as current/stale and clean/vulnerable. Native-provider evidence is retained with its inventory mode rather than being incorrectly treated as reproducible without rerunning the relevant provider inventory.

For Poetry/PDM, the validated structured-lock results that produced the exact scanned BOM are retained for dependency-path correlation. Direct and transitive ambiguity-derived findings remain possible evidence with `?dependency` hops; resolved and possible alternative paths for the same locked package occurrence are consolidated rather than duplicated.

OSV-Scanner exit code `1` is treated as a valid scan containing findings, not as scanner failure.

For explicitly registered projects, the same preview/apply boundary is available fleet-wide:

```sh
upm projects audit
upm projects audit --native
upm projects audit --apply
upm projects audit --native --apply
upm projects audit --apply --json
```

Valid real scans persist evidence inside each scanned project, so a subsequent `upm projects status` can surface clean/vulnerable/stale states without silently rescanning.

## SBOM export

CycloneDX 1.7 JSON:

```sh
upm sbom .
upm sbom . --native
upm sbom . --output bom.cdx.json
```

SPDX 2.3 JSON:

```sh
upm sbom . --format spdx
upm sbom . --format spdx --native
```

Registry resolutions receive canonical Package URLs where native provenance supports that identity. Git/path/local packages retain deterministic local identities rather than fabricated registry provenance.

Native relationship enrichment covers Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Provider-specific uncertainty remains explicit: uv and Poetry/PDM do not flatten conditional/ambiguous relationships into unconditional dependencies, Yarn only admits active-root-reachable stored resolutions, and registry identity is only emitted where provenance supports it. CycloneDX can record provider-specific omission/reachability properties; SPDX 2.3 conservatively omits relationships whose original conditions cannot be represented without changing their meaning.

## Cache and store integrity

Cache integrity is separate from project-state integrity.

### Package-cache verification

```sh
upm verify . --cache
```

For Go, UPM delegates to `go mod verify` using a temporary adjacent modfile/sum pair so project `go.mod`/`go.sum` are isolated from writes.

### Shared-store non-mutating checks

```sh
upm cache check
upm cache check --manager pnpm
```

The pnpm provider uses `pnpm store status` to detect modified content-addressable-store packages.

### Explicit maintenance

```sh
upm cache verify
upm cache verify --apply
upm cache prune --manager pnpm
upm cache prune --manager uv
upm cache clean --manager npm
```

Maintenance is preview-first. `cache verify` remains distinct from pruning/full clean because npm verification itself can garbage-collect unneeded cache data. Storage observations never trigger cleanup automatically.

## Storage and physical provenance

Project artifact storage:

```sh
upm storage .
upm projects storage
```

Machine-wide cache/store storage:

```sh
upm cache storage
upm cache storage --manager go --manager cargo
```

Current project-local roots include Node `node_modules`, Python `.venv`/`__pypackages__` environments where configured, and Cargo `target`.

Shared cache roots include Go, npm, pnpm, uv, and Cargo stores. Symlinks are not followed and hardlinked physical bytes are counted once where inode identity is available.

UPM also has provenance attribution for selected Go module-cache directories and Cargo registry/git source directories. Attributed and unattributed cache bytes remain separate. **Unattributed bytes are not labeled reclaimable.**

## Safe repair

```sh
upm repair .
upm repair . --component frontend
upm repair . --apply
```

Repair starts from deep installed-state findings and only emits plans that map to an authoritative locked/frozen native synchronization operation. Malformed manifests, manager conflicts, and intentional integrity-baseline changes remain diagnosis-only.

Applied repair writes a mutation receipt.

## Native manager escape hatch

```sh
upm exec --path . --component frontend -- view react version
upm exec --path . --component frontend --apply -- view react version
```

`exec` is argv-based, not a shell. It retains component selection, manager-ownership checks, exact executable resolution, preview/apply semantics, and post-command doctor verification. Applied exec writes a redacted mutation receipt.

## Project workflows

Explicit tasks use argv arrays and dependency edges:

```toml
[tasks.lint]
command = ["python", "-m", "compileall", "src"]

[tasks.test]
command = ["python", "-m", "unittest"]
depends = ["lint"]
```

```sh
upm tasks .
upm run test .
upm run test . --apply
```

UPM rejects shell command strings, dependency cycles, unknown task dependencies, and working directories that escape the project root.

Native fallback supports Node package scripts, Cargo `build/check/run/test`, and Go `build/test/vet/run`. If multiple components expose the same task, `--component` is required.

Task execution is intentionally not described as a complete package-state mutation receipt: user-authored tasks may create arbitrary build/test outputs outside UPM's native manifest/lock-state evidence model.

## Initialize projects

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
upm init service --ecosystem go --module example.com/service
```

Initialization is preview-first and targets must be new or empty inside the selected root. Applied initialization writes a receipt that records newly created native project state.

## Registered projects and fleet views

UPM monitors only projects explicitly registered by the user; there is no home-directory crawler.

```sh
upm projects add ~/code/my-app
upm projects list
upm projects status
upm projects audit
upm projects policy
upm projects inventory --native
upm projects duplicates --native
upm projects impact some-package --native
upm projects storage
upm projects remove ~/code/my-app
```

The default registry is `~/.upm/projects.json`; `--registry` can override it.

Evidence-aware fleet status reuses the same local project status model and does not run scanners or relationship providers. Missing/unreadable registered projects are explicit fleet blockers.

Native fleet inventory, duplicate correlation, and impact now cover all eight public provider families while retaining provider-specific scope labels and project/component context. pnpm preserves logical workspace/alias/scope/dedupe occurrences; Yarn fleet inventory excludes inactive stored locators; Poetry/PDM fleet inventory carries `unconditional`, `conditional`, or `possible` certainty and excludes orphan structured-lock records. Duplicate observations are never automatically labeled reclaimable.

## Project policy

Policy lives in `upm.toml` and is enforcement-only. Examples include requiring native state, integrity/advisory evidence, verification coverage, manager allow/deny lists, and health/vulnerability budgets.

```toml
[policy]
require_lockfiles = true
require_integrity_snapshot = true
require_native_verification = true
require_cache_integrity_verification = true
allowed_managers = ["pnpm", "uv", "cargo", "go"]
max_errors = 0
max_warnings = 2
```

```sh
upm policy .
upm policy . --deep
upm projects policy
```

Policy evaluation does not rewrite native state or trigger hidden scanners.

## Design principles

1. **Native tools remain authoritative.** UPM orchestrates instead of becoming another resolver.
2. **Normalize observations, not ecosystem semantics away.** Meaningful differences remain visible.
3. **Preview before mutation or network access.** Applied operations/scans are explicit.
4. **Record mutations truthfully.** Applied package/init/repair/exec/in-root workspace workflows retain redacted before/after native-state evidence; out-of-root mutations are not mislabeled complete.
5. **Refuse ambiguity.** Manager, workspace, component, and universal-lock fork uncertainty is never guessed away.
6. **Separate integrity layers.** Structural state, native semantic verification, installed drift, advisory evidence, receipt history, cache corruption, and storage are distinct signals.
7. **Prefer explicit uncertainty.** Unsupported or conditional evidence is surfaced rather than converted to fabricated certainty.
8. **Measurement is not cleanup.** Duplicate versions/cache bytes are observations, not deletion instructions.
9. **Policy is enforcement, not repair.** Evaluation never rewrites project state.
10. **Local-first by default.** Relationship queries default to local/offline modes where native tooling supports that contract; no hosted UPM service or GitHub Actions is required.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the focused documents under [`docs/`](docs/) for provider, workspace, security, receipt, SBOM, and cache/provenance boundaries.