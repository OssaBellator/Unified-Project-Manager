# Unified Project Manager

Unified Project Manager (`upm`) is an experimental local-first control plane for development projects. It does **not** replace npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, or Go modules. Native package managers and toolchains remain authoritative for dependency resolution and project mutation; UPM discovers, normalizes, plans, delegates, verifies, correlates, and applies policy to their state.

The current implementation targets Python 3.11+ and has no runtime dependencies outside the standard library.

## What works today

UPM currently supports:

- mixed-repository discovery for Node, Python, Rust, and Go projects;
- normalized direct dependencies, concrete resolved inventory where authoritative native state permits it, manager ownership, and toolchain requirements;
- structural health checks for malformed manifests, lock/state conflicts, missing tools, toolchain-version drift, and declared Node package-manager-version drift;
- native syntax/integrity checks for npm JSON, uv/Poetry/PDM TOML, Cargo TOML, and Go module state;
- SHA-256 integrity snapshots for discovered native project-state files;
- documented non-mutating native verification through `upm verify`;
- Go package-cache content verification through `upm verify --cache`;
- opt-in deep installed-state checks for npm `node_modules` and local Python `.venv` metadata;
- a unified `upm status` view combining health, policy, integrity snapshot state, verifier coverage, dependency counts, and optional storage measurement;
- cross-ecosystem policy in `upm.toml`, plus fleet policy across explicitly registered projects;
- preview-first native `init`, `install`, `sync`, `add`, `remove`, and safe repair operations;
- a preview-first manager-scoped `upm exec` escape hatch for native commands not covered by the common command vocabulary;
- direct/resolved/native `graph`, `why`, `impact`, and duplicate-analysis views where authoritative graph information is available;
- safe task DAGs in `upm.toml`, plus native Node/Cargo/Go task discovery;
- project-local and registered-project storage accounting without destructive cleanup;
- an explicit user-level project registry for fleet health, policy, inventory, impact, duplicate analysis, and storage views;
- deterministic CycloneDX 1.7 SBOM export from concrete resolved native inventory.

No GitHub Actions workflows are used. Validation is local and script-driven.

## Local validation

```sh
sh ./scripts/check.sh
```

That command runs `compileall` and the standard-library `unittest` suite. No external test framework or CI service is required.

Run without installing:

```sh
PYTHONPATH=src python3 -m unified_project_manager status .
```

Or install it in an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
upm status .
```

## Unified project status

`status` is the high-level project view. The cheap/default mode does not execute native verifiers or measure storage:

```sh
upm status .
upm status . --json
```

It reports discovered components/ecosystems/managers, direct and resolved dependency counts, doctor health, configured policy result, `.upm/state.json` presence, and how many components have a configured non-mutating native verifier.

Installed-environment traversal and disk measurement are explicit:

```sh
upm status . --deep
upm status . --storage
upm status . --deep --storage
```

A configured policy violation makes `status` exit non-zero even if structural doctor checks otherwise pass.

## Discover, inspect, and verify

```sh
upm discover .
upm graph .
upm graph . --resolved
upm graph . --native
upm why zod .
upm why zod . --resolved
upm why example.com/module . --native
upm impact example.com/module . --native
upm duplicates .
upm duplicates . --resolved
upm doctor .
upm doctor . --deep
upm verify .
upm verify . --preview
upm verify . --cache
```

Component keys use `<relative-path>:<ecosystem>`, for example `frontend:node`, `backend:python`, `engine:rust`, or `service:go`.

`--resolved` views are populated only from native state UPM can safely interpret as concrete resolved inventory. Native graph views use authoritative ecosystem commands rather than treating checksum files as dependency graphs.

`upm verify` only runs verification commands configured as non-mutating. Current paths include npm dry-run CI, Bun frozen dry-run, `uv lock --check`, `pdm lock --check`, locked Cargo metadata, and `go mod tidy -diff`. Unsupported components are reported as skipped rather than probed with a potentially mutating command.

`upm verify --cache` currently has deliberately narrow coverage: for Go it uses `go mod verify` with a temporary adjacent modfile so the project's real `go.mod`/`go.sum` are isolated from writes. Other ecosystems are explicitly skipped until UPM has an authoritative safe cache-content verification path for them.

## Go module semantics

Go support deliberately does not pretend `go.sum` is a universal lockfile. UPM treats `go.mod` as module/dependency/toolchain declaration and `go.sum` as checksum/integrity state.

For authoritative selected-module and relationship information, native graph mode uses Go tooling such as the read-only selected build list and module graph. This lets UPM keep selected versions, required edge versions, replacements, and local replacements distinct instead of inferring them from checksum rows.

## Integrity snapshots

```sh
upm snapshot .
# writes .upm/state.json

upm doctor .
```

`.upm/state.json` records root-relative native manifest/state paths, SHA-256 digests, sizes, and component identity. It is **not** a universal dependency lockfile. `upm snapshot` explicitly accepts the reviewed current state as a new integrity baseline.

## Cross-ecosystem project policy

Policy lives alongside tasks in `upm.toml` and is read-only enforcement:

```toml
[policy]
require_lockfiles = true
require_integrity_snapshot = true
require_native_verification = true
allowed_managers = ["pnpm", "uv", "cargo", "go"]
max_errors = 0
max_warnings = 2
```

Supported rules currently include:

- `require_lockfiles`: every component must expose a discovered native lock/checksum state file;
- `require_integrity_snapshot`: `.upm/state.json` must exist;
- `require_native_verification`: every component must have a configured non-mutating verifier;
- `allowed_managers` / `denied_managers`: constrain manager ownership across ecosystems;
- `max_errors` / `max_warnings`: bound doctor findings.

Evaluate one repository or every explicitly registered repository:

```sh
upm policy .
upm policy . --deep
upm projects policy
upm projects policy --deep
```

Invalid policy configuration is an explicit configuration error. Missing registered roots and per-project policy parse failures are surfaced without stopping evaluation of the rest of the fleet.

## Preview-first package operations

Mutating operations preview the exact native command by default:

```sh
upm add react --component frontend
upm sync --component backend
upm install --all
```

Execute only after reviewing the plan:

```sh
upm add react --component frontend --apply
upm sync --component backend --apply
upm sync --all --apply
```

Applied operations re-discover and verify the project unless `--no-verify` is supplied. UPM refuses mutation planning when manager ownership is ambiguous.

Current delegation includes npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip-install workflows, Cargo, and Go modules. For Go, install/sync hydrate module state with native Go semantics; consistency belongs to native verification rather than a fabricated lockfile operation.

## Native manager escape hatch

The common vocabulary intentionally remains leaky. `exec` lets a developer run manager-specific functionality without bypassing UPM's component selection and manager-ownership checks:

```sh
upm exec --path . --component frontend -- view react version
upm exec --path . --component backend -- tree
```

These are previews. Execution still requires `--apply`:

```sh
upm exec --path . --component frontend --apply -- view react version
```

`exec` is **not a shell**. UPM constructs an argv vector prefixed with the selected component's authoritative manager, resolves that manager executable explicitly, runs it in the component directory, captures output, and runs post-command doctor verification by default. Conflicting lockfiles/manager ownership are refused rather than guessed.

## Toolchain and manager version health

`doctor` checks executable presence and compares active versions with declared requirements where UPM can interpret the syntax safely. Current support covers common Node semver ranges, common Python specifiers, Rust minimum versions, Go minimum versions, and declared npm/pnpm/Yarn/Bun versions. Unsupported syntax is informational/unverified rather than guessed pass/fail.

## Project tasks

UPM tasks use argv arrays instead of shell command strings:

```toml
[tasks.lint]
command = ["python", "-m", "compileall", "src"]

[tasks.test]
command = ["python", "-m", "unittest"]
depends = ["lint"]
```

Then:

```sh
upm tasks .
upm run test .
upm run test . --apply
```

Task cycles, unknown dependencies, root-escaping working directories, and shell-string commands are rejected before execution. Native fallback supports Node package scripts, Cargo core tasks, and Go build/test/vet/run tasks; ambiguous native task names require `--component`.

## Storage accounting

UPM measures known project-local artifact directories without deleting anything:

```sh
upm storage .
upm projects storage
```

Current measurement covers Node `node_modules`, Python `.venv`/`__pypackages__`, and Cargo `target`. Symlinks are not followed and hardlinked files are counted once when inode information is available, including across registered projects. A reported byte count is **not** a claim that the space is safely reclaimable.

## Safe repair

`repair` starts from a deep diagnosis and only plans repairs UPM can map to an authoritative locked/frozen native sync:

```sh
upm repair .
upm repair . --component frontend
upm repair . --apply
```

Malformed manifests, conflicting package managers/lockfiles, and intentional snapshot changes are diagnosis-only. UPM does not guess away user intent.

## Initialize projects

Initialization delegates to native generators and is preview-first:

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
upm init service --ecosystem go --module example.com/service
```

Current generic initializer paths are npm/pnpm/Bun, uv, Cargo, and `go mod init`. Targets must be new or empty and remain inside the selected root.

## Local project registry

UPM monitors only projects explicitly registered by the user; it does not crawl the home directory:

```sh
upm projects add ~/code/my-app
upm projects list
upm projects status
upm projects policy
upm projects inventory
upm projects duplicates
upm projects impact example.com/module --native
upm projects storage
upm projects remove ~/code/my-app
```

The default registry is `~/.upm/projects.json`; `--registry` can override it for isolated environments/tests.

## CycloneDX SBOM export

```sh
upm sbom .
upm sbom . --native
upm sbom . --output bom.cdx.json
```

UPM emits deterministic CycloneDX 1.7 JSON from concrete native-resolved inventory. Registry resolutions receive ecosystem Package URLs; Git/path/local resolutions retain deterministic UPM identities rather than fabricated registry provenance. Native Go SBOM mode uses selected module versions rather than converting `go.sum` rows into package components.

SPDX export remains deferred until its richer relationship model can be represented explicitly.

## Design principles

1. **Native managers remain authoritative.** UPM delegates resolution/mutation instead of reimplementing ecosystem semantics.
2. **Normalize observations, not lockfiles.** Native manifests/state stay first-class; UPM builds a common graph above them.
3. **Preview before mutation or arbitrary execution.** Native mutations, tasks, and manager escape-hatch commands require explicit `--apply`.
4. **Refuse ambiguity.** Conflicting managers, native state, component selectors, task targets, and unsafe repair cases are errors instead of guesses.
5. **Prefer explicit uncertainty to false compatibility.** Unsupported version syntax or verifier coverage is surfaced as unverified/skipped.
6. **Deep/expensive work is explicit.** Installed-environment traversal and storage measurement are opt-in from the unified status view.
7. **Do not equate duplication/storage with corruption.** Duplicate versions and byte counts are observations, not automatic deletion candidates.
8. **Policy is enforcement, not mutation.** Project/fleet policy changes exit status and diagnostics but does not rewrite native state.
9. **Local-first by default.** Health, policy, workflows, storage, and fleet inventory work without a hosted service or GitHub Actions.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for architecture, safety boundaries, and milestone status.
