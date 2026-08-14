# Unified Project Manager

Unified Project Manager (`upm`) is an experimental package-manager-agnostic control plane for development projects. It does **not** replace npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, or Cargo. Native package managers remain authoritative for dependency resolution and project mutation; UPM discovers, normalizes, plans, delegates, verifies, and correlates their state.

The current implementation targets Python 3.11+ and has no runtime dependencies outside the standard library.

## What works today

UPM currently supports:

- mixed-repository discovery for Node, Python, and Rust projects;
- normalized direct dependencies, resolved package inventory, package-manager ownership, and toolchain requirements;
- structural health checks for malformed manifests, lockfile conflicts, manager mismatches, and missing tools;
- native lockfile syntax checks for npm, uv/Poetry/PDM, and Cargo formats that are JSON/TOML parseable;
- npm manifest-vs-lock root dependency drift detection;
- SHA-256 integrity snapshots for native manifests and lockfiles;
- opt-in deep installed-state checks for npm `node_modules` and local Python `.venv` metadata;
- preview-first native `init`, `install`, `sync`, `add`, and `remove` operations;
- preview-first repair plans for installed-state drift using the authoritative manager's locked/frozen sync;
- multi-component `install --all` and `sync --all` planning;
- direct and resolved `graph`, `why`, and `duplicates` queries;
- a user-level registry for explicitly registered projects and fleet health status;
- resolved package duplication aggregation across registered projects in the registry API;
- CycloneDX 1.7 SBOM export from resolved native lockfile inventory;
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

## Discover and inspect

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
```

Component keys use `<relative-path>:<ecosystem>`, for example `frontend:node`, `backend:python`, or `engine:rust`.

`--resolved` views are populated from native lockfiles UPM can parse safely. They represent observations from the authoritative lockfile, not a second UPM resolver.

`doctor --deep` is intentionally opt-in because it traverses installed environments. The first deep checks cover npm physical `node_modules` locations and local Python `.venv` `dist-info` metadata.

## Integrity snapshots

```sh
upm snapshot .
# writes .upm/state.json

upm doctor .
```

`.upm/state.json` records root-relative native manifest/lockfile paths, SHA-256 digests, sizes, and component identity. It is **not** a universal dependency lockfile. UPM reports changed, missing, newly discovered, invalid, or unsupported snapshot state; `upm snapshot` explicitly accepts the current state as the new baseline.

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

## Safe repair

`repair` starts from a deep diagnosis and only plans repairs UPM can map to an authoritative locked/frozen native sync:

```sh
upm repair .
upm repair . --component frontend
upm repair . --apply
```

Malformed manifests, conflicting package managers, conflicting lockfiles, and intentional snapshot changes are **not** auto-repaired. UPM reports them and leaves the decision to the developer.

## Initialize projects

Initialization delegates to native generators and is also preview-first:

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
```

Add `--apply` to execute. Current defaults are npm for Node, uv for Python, and Cargo for Rust. Supported generic initializers are npm/pnpm/Bun, uv, and Cargo.

For safety, the target must be new or empty and must remain inside the current root. Existing projects are not silently adopted or overwritten.

## Local project registry

UPM only monitors projects explicitly registered by the user; it does not crawl the home directory:

```sh
upm projects add ~/code/my-app
upm projects list
upm projects status
upm projects status --deep
upm projects remove ~/code/my-app
```

The default registry is `~/.upm/projects.json`. A custom path can be supplied with `--registry`, which also keeps the feature easy to test without touching user state.

## CycloneDX SBOM export

```sh
upm sbom .
upm sbom . --output bom.cdx.json
```

The first exporter emits deterministic CycloneDX 1.7 JSON from concrete versions found in parseable native lockfiles. Registry resolutions receive Package URLs (npm, PyPI, Cargo). Git/path/local resolutions are retained as components with deterministic UPM `bom-ref` values rather than being mislabeled as registry packages.

SPDX export is intentionally deferred until UPM can model the richer SPDX object graph correctly.

## Design principles

1. **Native managers remain authoritative.** UPM delegates dependency resolution and mutation instead of reimplementing ecosystem semantics.
2. **Normalize observations, not lockfiles.** Native manifests and lockfiles stay first-class; UPM builds a common graph above them.
3. **Preview before mutation.** Native commands are visible before execution and require explicit `--apply`.
4. **Refuse ambiguity.** Conflicting managers, lockfiles, component selectors, and unsafe repair cases are errors instead of guesses.
5. **Deep checks are explicit.** Expensive installed-environment inspection is opt-in.
6. **Do not equate duplication with corruption.** Duplicate declarations/resolutions are surfaced for analysis, not automatically deleted.
7. **Local-first by default.** Project health and the project registry work without a hosted service or GitHub Actions.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for architecture, safety boundaries, and milestone status.
