# Unified Project Manager

Unified Project Manager (`upm`) is an experimental **local-first control plane over native project and package managers**.

It does not replace npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip, Cargo, or Go modules. Native tools remain authoritative for dependency resolution, lock/state semantics, caches, and project mutation. UPM sits above them to provide one place to discover projects, inspect health, apply policy, preview operations, run workflows, correlate repositories, measure storage, and ask native tools for information UPM should not reimplement.

The current implementation targets Python 3.11+ and has no runtime dependencies outside the standard library.

## Current scope

UPM currently covers four ecosystem families:

| Ecosystem | Native managers/tooling | Current control-plane coverage |
| --- | --- | --- |
| Node | npm, pnpm, Yarn, Bun | discovery, manager ownership, direct deps, npm resolved inventory, package scripts, operations, version checks, native verification, cache/store coverage |
| Python | uv, Poetry, PDM, pip | PEP 621/dependency groups/Poetry/requirements discovery, resolved lock inventory, operations, toolchain checks, native verification, installed `.venv` checks |
| Rust | Cargo | manifest/workspace deps, `Cargo.lock` inventory, operations, tasks, native verification, storage |
| Go | Go modules | `go.mod` discovery, checksum state, native selected-module graph, replacements, impact, cache verification, provenance, tasks, operations |

Across those ecosystems UPM provides:

- recursive mixed-repository discovery;
- normalized components, manager ownership, direct dependencies, resolved inventory where trustworthy, and toolchain requirements;
- structural `doctor` findings and portable SHA-256 state snapshots;
- live toolchain and Node package-manager version checks;
- preview-first package operations, repair, initialization, native-manager escape-hatch commands, and project tasks;
- explicit native semantic verification and cache/store integrity checks;
- direct/resolved/native graph, why, duplicate, and impact views;
- project policy and registered-project fleet policy;
- project, fleet, and machine-wide cache/storage accounting;
- CycloneDX 1.7 export, including authoritative Go native enrichment;
- JSON output for automation without requiring a hosted control plane.

**No GitHub Actions workflows are used.** Validation is local and script-driven.

## Local validation

```sh
sh ./scripts/check.sh
```

The script runs `compileall` and the standard-library `unittest` suite.

Run without installing:

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

## Unified status

`status` is the cheap, composed project view:

```sh
upm status .
upm status . --json
```

It reports:

- discovered components, ecosystems, and managers;
- direct/resolved dependency counts;
- structural doctor health;
- project policy result;
- `.upm/state.json` presence;
- non-mutating native-verifier coverage;
- cache-integrity coverage and whether the available mechanism can mutate shared cache state.

Expensive filesystem traversal stays explicit:

```sh
upm status . --deep
upm status . --storage
upm status . --deep --storage
```

`status` reports verifier **coverage** but does not silently execute native graph queries, cache checks, or mutating maintenance commands.

## Discovery and project health

```sh
upm discover .
upm doctor .
upm doctor . --deep
upm snapshot .
```

`doctor` checks structural state, manager ownership, lock/state conflicts, native parse errors, tool availability, toolchain/version drift, integrity snapshots, and other cross-ecosystem findings.

`doctor --deep` additionally inspects installed state where UPM has a sufficiently reliable mapping today: npm `node_modules` and local Python `.venv` metadata.

`snapshot` writes `.upm/state.json`, recording root-relative native project-state paths, sizes, component identity, and SHA-256 hashes. It is an observation baseline, **not** a replacement dependency lockfile.

## Native semantic verification

UPM keeps structural parsing separate from authoritative native semantic checks:

```sh
upm verify .
upm verify . --preview
```

Configured non-mutating verification paths currently include:

- npm: CI dry-run with scripts/audit/funding disabled;
- Bun: frozen dry-run with scripts disabled;
- uv: `uv lock --check`;
- PDM: `pdm lock --check`;
- Cargo: locked metadata;
- Go: `go mod tidy -diff`.

Unsupported managers are skipped rather than probed with a command UPM cannot classify safely.

For component-scoped Go verification and graph queries UPM sets `GOWORK=off`; an enclosing `go.work` therefore cannot silently change the meaning of an individually discovered `go.mod` component. First-class Go workspace modeling is a separate future feature.

## Cache and store integrity

Cache integrity is a separate layer from manifest/lock consistency and installed-state drift.

### Go module cache content

```sh
upm verify . --cache
```

For Go, UPM delegates to `go mod verify` while copying `go.mod`/`go.sum` to a temporary adjacent modfile pair. The real project files remain isolated from writes and temporary files are removed afterward. Go may still populate shared-cache metadata while resolving the build list, so this is not described as perfectly side-effect-free.

### Shared-store read-only checks

```sh
upm cache check
upm cache check --manager pnpm
```

The first shared-store integrity check uses `pnpm store status`, which detects modified packages in pnpm's content-addressable store without being modeled as maintenance.

### Shared-cache maintenance verification

Current npm cache verification is deliberately preview-first:

```sh
upm cache verify
upm cache verify --json
upm cache verify --apply
```

The preview exposes `npm cache verify` and its effect. `--apply` is required because npm verification also garbage-collects unneeded cache data; UPM will not smuggle that maintenance side effect under a supposedly read-only check.

## Storage accounting

Storage measurement never implies safe deletion.

### Project-local artifacts

```sh
upm storage .
upm projects storage
```

Current project-local roots include:

- Node `node_modules`;
- Python `.venv` and `__pypackages__`;
- Cargo `target`.

Symlinks are not followed. Hardlinked files are counted once where inode identity is available, including across registered projects.

### Machine-wide native caches/stores

```sh
upm cache storage
upm cache storage --manager pnpm
upm cache storage --manager go --manager cargo
```

UPM currently obtains or derives authoritative cache/store roots for:

- Go `GOMODCACHE` and `GOCACHE`;
- npm's configured cache path;
- pnpm's configured content-addressable store path;
- uv's configured cache directory;
- Cargo's `CARGO_HOME/registry` and `CARGO_HOME/git` stores.

Shared physical hardlinks are deduplicated across measured roots. JSON output explicitly reports `reclaimable: false`; cache cleanup remains ecosystem-specific future work.

## Dependency views

### Direct and lock-resolved observations

```sh
upm graph .
upm graph . --resolved
upm why zod .
upm why zod . --resolved
upm duplicates .
upm duplicates . --resolved
```

`--resolved` only uses native state UPM can safely interpret as concrete resolution inventory. It is not a second resolver.

### Authoritative native graph

Go currently has the first live native transitive graph provider:

```sh
upm graph . --native
upm graph . --native --preview
upm why example.com/module . --native
upm impact example.com/module . --native
```

UPM keeps distinct:

- the selected Go build list;
- the version required by each `go mod graph` edge;
- the selected version that wins;
- versioned replacements and local replacements;
- module provenance such as Go version, module sums, and VCS origin when Go exposes it.

`impact --native` is explicitly **module-requirement impact**. It computes reverse reachability through selected module-version requirement edges. It does not claim source-code, API, import-symbol, or runtime-call impact.

## Go module semantics

Go is intentionally not forced into a lockfile abstraction:

- `go.mod` is module/dependency/toolchain declaration;
- `go.sum` is checksum state and may contain versions not selected in the build list;
- authoritative selected-module inventory comes from native Go queries;
- `go mod why -m` answers why a module is needed through the package import graph;
- `go mod graph` exposes module requirement edges.

Native CycloneDX enrichment uses the selected build list instead of turning every `go.sum` row into a component.

## Project policy

Policy lives in `upm.toml` and is enforcement-only:

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

Current rules include:

- `require_lockfiles`;
- `require_integrity_snapshot`;
- `require_native_verification`;
- `require_cache_integrity_verification` — requires a configured authoritative cache-integrity mechanism, but does not execute it;
- `allowed_managers` / `denied_managers`;
- `max_errors` / `max_warnings`.

Evaluate one project or every registered project:

```sh
upm policy .
upm policy . --deep
upm projects policy
upm projects policy --deep
```

Policy affects diagnostics and exit status. It does not rewrite native state to force compliance.

## Preview-first package operations

```sh
upm add react --component frontend
upm sync --component backend
upm install --all
```

These only show exact native commands. Execution requires `--apply`:

```sh
upm add react --component frontend --apply
upm sync --component backend --apply
upm sync --all --apply
```

UPM refuses mutations when native manager ownership is ambiguous.

Current delegation includes npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip-install workflows, Cargo, and Go modules.

## Safe repair

```sh
upm repair .
upm repair . --component frontend
upm repair . --apply
```

Repair starts from deep installed-state findings and only produces a plan when UPM can map the finding to an authoritative locked/frozen native synchronization operation. Malformed manifests, ownership conflicts, and intentional integrity-baseline changes remain diagnosis-only.

## Native manager escape hatch

For native functionality outside the common vocabulary:

```sh
upm exec --path . --component frontend -- view react version
upm exec --path . --component frontend --apply -- view react version
```

`exec` is argv-based, not a shell. It retains UPM component selection, manager-ownership checks, exact executable resolution, preview/apply semantics, and post-command doctor verification.

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

## Initialize projects

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
upm init service --ecosystem go --module example.com/service
```

Initialization is preview-first and targets must be new or empty inside the selected root.

## Registered projects and fleet views

UPM monitors only projects explicitly registered by the user:

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

The default registry is `~/.upm/projects.json`; `--registry` can override it.

Native fleet impact retains project/component/root-path context and is still labeled module-requirement impact rather than source/API impact.

## CycloneDX SBOM

```sh
upm sbom .
upm sbom . --native
upm sbom . --output bom.cdx.json
```

UPM emits deterministic CycloneDX 1.7 JSON from concrete authoritative inventory.

- npm/PyPI/Cargo registry resolutions receive Package URLs;
- Git/path/local resolutions retain deterministic UPM identities rather than fabricated registry provenance;
- native Go mode uses canonical Go Package URLs for versioned selected modules;
- local Go replacements remain versionless deterministic UPM identities;
- stable Go provenance (module sums, Go version, indirect flag, VCS origin) is retained as properties while machine-local cache paths are excluded from portable SBOM identity.

SPDX remains deferred until its richer relationship model can be implemented explicitly rather than aliased to CycloneDX data.

## Design principles

1. **Native tools remain authoritative.** UPM orchestrates instead of becoming another resolver.
2. **Normalize observations, not ecosystem semantics away.** Leaky differences are preserved when they matter.
3. **Preview before mutation.** Package changes, arbitrary native commands, tasks, and cache maintenance require explicit application.
4. **Refuse ambiguity.** Conflicting managers/state/component targets are errors, not guesses.
5. **Separate integrity layers.** Structural state, native semantic verification, installed drift, cache corruption, and disk usage are different signals.
6. **Prefer explicit uncertainty.** Unsupported syntax/checks are surfaced as unverified/skipped instead of fabricated success.
7. **Measurement is not cleanup.** Duplicate versions and cache/storage bytes are observations, not deletion instructions.
8. **Policy is enforcement, not repair.** Evaluating policy never rewrites the project.
9. **Expensive work is explicit.** Status stays cheap; deep scans, native graphs, cache checks, and disk measurement are opt-in.
10. **Local-first by default.** No hosted service or GitHub Actions is required for the core control plane.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for architecture and safety boundaries.
