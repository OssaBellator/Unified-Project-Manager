# Unified Project Manager

Unified Project Manager (`upm`) is an experimental package-manager-agnostic control plane for development projects. It does **not** replace npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, or Go modules. Native package managers and toolchains remain authoritative for dependency resolution and project mutation; UPM discovers, normalizes, plans, delegates, verifies, and correlates their state.

The current implementation targets Python 3.11+ and has no runtime dependencies outside the standard library.

## What works today

UPM currently supports:

- mixed-repository discovery for Node, Python, Rust, and Go projects;
- normalized direct dependencies, resolved package inventory where native state represents a concrete resolution, package-manager ownership, and toolchain requirements;
- structural health checks for malformed manifests, lockfile/manager conflicts, missing tools, declared toolchain-version drift, and declared Node package-manager-version drift;
- native lockfile syntax checks for npm, uv/Poetry/PDM, and Cargo formats that are safely JSON/TOML parseable;
- npm manifest-vs-lock root dependency drift detection;
- SHA-256 integrity snapshots for discovered native manifests/state files;
- documented non-mutating native verification commands through `upm verify`;
- opt-in deep installed-state checks for npm `node_modules` and local Python `.venv` metadata;
- preview-first native `init`, `install`, `sync`, `add`, and `remove` operations;
- preview-first repair plans for installed-state drift using the authoritative manager's locked/frozen sync where UPM has a safe mapping;
- multi-component `install --all` and `sync --all` planning;
- direct and resolved `graph`, `why`, and `duplicates` queries;
- safe project task DAGs in `upm.toml`, plus native Node/Cargo/Go task discovery;
- project-local and registered-project storage accounting without destructive cleanup;
- a user-level registry for explicitly registered projects, fleet health, resolved inventory, duplicate analysis, and storage views;
- CycloneDX 1.7 SBOM export from concrete resolved native inventory;
- human-readable and JSON output for automation and tooling.

No GitHub Actions workflows are used. Validation is local and script-driven.

## Local validation

```sh
sh ./scripts/check.sh
```

That command runs `compileall` and the standard-library `unittest` suite. No external test framework or CI service is required.

Run the CLI without installing it:

```sh
PYTHONPATH=src python3 -m unified_project_manager doctor .
```

Or install it in an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
upm doctor .
```

## Discover, inspect, and verify

```sh
upm discover .
upm graph .
upm graph . --resolved
upm why zod .
upm why zod . --resolved
upm duplicates .
upm duplicates . --resolved
upm doctor .
upm doctor . --deep
upm verify .
upm verify . --preview
```

Component keys use `<relative-path>:<ecosystem>`, for example `frontend:node`, `backend:python`, `engine:rust`, or `service:go`.

`--resolved` views are populated only from native state UPM can interpret as concrete resolved inventory. They are observations from authoritative native state, not a UPM resolver.

`upm verify` runs only verification commands that are configured as non-mutating. Current examples include npm dry-run CI, Bun frozen dry-run, `uv lock --check`, `pdm lock --check`, locked Cargo metadata, and `go mod tidy -diff`. Components without a sufficiently safe native verification path are reported as skipped rather than probed with a potentially mutating command.

`doctor --deep` is intentionally opt-in because it traverses installed environments. Current deep checks cover npm physical `node_modules` locations and local Python `.venv` `dist-info` metadata.

## Go module semantics

Go support deliberately does not pretend `go.sum` is a universal lockfile. UPM treats:

- `go.mod` as the module/dependency/toolchain declaration;
- the `go` directive as a minimum Go toolchain requirement;
- `go.sum` as checksum/integrity state;
- `go mod tidy -diff` as the current non-mutating native consistency check.

Because `go.sum` can retain checksums for module versions that are not in the selected build list, UPM does **not** convert every `go.sum` entry into resolved dependency inventory or SBOM components.

## Integrity snapshots

```sh
upm snapshot .
# writes .upm/state.json

upm doctor .
```

`.upm/state.json` records root-relative native manifest/state-file paths, SHA-256 digests, sizes, and component identity. It is **not** a universal dependency lockfile. UPM reports changed, missing, newly discovered, invalid, or unsupported snapshot state; `upm snapshot` explicitly accepts the current state as the new baseline.

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

Applied operations re-discover and verify the project unless `--no-verify` is supplied. UPM refuses to plan mutations when manager ownership is ambiguous, such as conflicting lockfiles or manifest/lockfile manager mismatches.

Current delegation includes:

| Ecosystem | Managers | Delegated operations |
| --- | --- | --- |
| Node | npm, pnpm, Yarn, Bun | install, frozen/immutable sync, add, remove |
| Python | uv, Poetry, PDM | install/sync, add, remove |
| Python requirements | pip | install only; manifest mutation is deliberately refused |
| Rust | Cargo | fetch/locked fetch, add, remove |
| Go | Go modules | module download, `go get` add, `@none` removal |

For Go, `install`/`sync` currently mean module-cache hydration with `go mod download`; consistency belongs to `upm verify` via `go mod tidy -diff`.

## Toolchain and manager version health

`doctor` checks executable presence and, when a component declares a version requirement, compares it with the active toolchain where UPM can safely interpret the syntax.

Current support covers common Node semver ranges, common Python version specifiers, Rust minimum versions, and Go minimum versions. Unsupported requirement syntax produces an informational `unverified` finding rather than a guessed pass/fail result.

For Node projects that declare npm/pnpm/Yarn/Bun versions, UPM also compares the active package-manager executable version with the project declaration. Exact declarations remain exact; explicit ranges remain ranges.

## Project tasks

UPM tasks use argv arrays instead of shell command strings:

```toml
# upm.toml
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

`run` is preview-first. Task dependency cycles, unknown dependencies, working-directory escapes, and shell-string commands are rejected before execution.

If a task is not defined in `upm.toml`, UPM can fall back to supported native tasks:

- Node package scripts through the authoritative npm/pnpm/Yarn/Bun manager;
- Cargo `build`, `check`, `run`, and `test`;
- Go `build`, `test`, `vet`, and `run`.

If multiple components expose the same native task, `--component` is required. An explicitly configured `upm.toml` task takes precedence over a native task of the same name.

## Storage accounting

UPM measures known project-local artifact directories without deleting anything:

```sh
upm storage .
upm storage . --json
```

The current measurement covers Node `node_modules`, Python `.venv`/`__pypackages__`, and Cargo `target`. Symlinks are not followed, and hardlinked files are counted once when filesystem inode information is available.

Fleet measurement shares hardlink identities across registered projects:

```sh
upm projects storage
```

A reported byte count is **not** a claim that the space is safely reclaimable. Cache cleanup and destructive deduplication require ecosystem-specific safety rules and remain separate future work.

## Safe repair

`repair` starts from a deep diagnosis and only plans repairs UPM can map to an authoritative locked/frozen native sync:

```sh
upm repair .
upm repair . --component frontend
upm repair . --apply
```

Malformed manifests, conflicting package managers, conflicting lockfiles, and intentional snapshot changes are **not** auto-repaired. UPM reports them and leaves the decision to the developer.

## Initialize projects

Initialization delegates to native generators and is preview-first:

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
upm init service --ecosystem go --module example.com/service
```

Add `--apply` to execute. Current generic initializer paths are npm/pnpm/Bun, uv, Cargo, and `go mod init`. Go initialization requires an explicit module path.

For safety, the target must be new or empty and must remain inside the current root. Existing projects are not silently adopted or overwritten.

## Local project registry

UPM only monitors projects explicitly registered by the user; it does not crawl the home directory:

```sh
upm projects add ~/code/my-app
upm projects list
upm projects status
upm projects status --deep
upm projects inventory
upm projects duplicates
upm projects storage
upm projects remove ~/code/my-app
```

The default registry is `~/.upm/projects.json`. A custom path can be supplied with `--registry`, which also keeps the feature easy to test without touching user state.

## CycloneDX SBOM export

```sh
upm sbom .
upm sbom . --output bom.cdx.json
```

The exporter emits deterministic CycloneDX 1.7 JSON from concrete versions in supported resolved native inventory. Registry resolutions receive Package URLs for npm, PyPI, and Cargo. Git/path/local resolutions are retained as components with deterministic UPM `bom-ref` values rather than being mislabeled as registry packages.

A Go Package URL mapping exists for future selected-module inventory, but `go.sum` checksums are deliberately not exported as resolved components.

SPDX export is intentionally deferred until UPM can model the richer SPDX object graph correctly.

## Design principles

1. **Native managers remain authoritative.** UPM delegates dependency resolution and mutation instead of reimplementing ecosystem semantics.
2. **Normalize observations, not lockfiles.** Native manifests and state stay first-class; UPM builds a common graph above them.
3. **Preview before mutation or arbitrary tasks.** Native mutation/task commands are visible before execution and require explicit `--apply`.
4. **Refuse ambiguity.** Conflicting managers, lockfiles, component selectors, task targets, and unsafe repair cases are errors instead of guesses.
5. **Prefer explicit uncertainty to false compatibility.** Unsupported version syntax or native verification paths are surfaced as unverified/skipped.
6. **Deep checks are explicit.** Expensive installed-environment inspection is opt-in.
7. **Do not equate duplication with corruption.** Duplicate declarations/resolutions and storage bytes are surfaced for analysis, not automatically deleted.
8. **Local-first by default.** Project health, workflows, storage accounting, and the project registry work without a hosted service or GitHub Actions.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for architecture, safety boundaries, and milestone status.
