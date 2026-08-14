# Unified Project Manager

Unified Project Manager (`upm`) is an experimental package-manager-agnostic control plane for development projects. It does **not** replace npm, pnpm, Bun, uv, Poetry, PDM, pip, or Cargo. Native package managers remain authoritative for dependency resolution and project mutation; UPM discovers, normalizes, plans, delegates, and verifies their work.

## Current vertical slice

UPM currently supports:

- recursive mixed-repository discovery while skipping install/build/cache directories;
- Node projects (`package.json`, npm/pnpm/Yarn/Bun lockfiles);
- Python projects (`pyproject.toml`, requirements files, uv/Poetry/PDM lockfiles);
- Rust projects (`Cargo.toml`, `Cargo.lock`);
- normalized direct dependency, scope, manager, and toolchain metadata;
- conflict detection for ambiguous package managers and lockfiles;
- dependency inspection with `graph`, `why`, and `duplicates`;
- integrity snapshots for native manifests and lockfiles;
- preview-first native `init`, `install`, `sync`, `add`, and `remove` operations;
- multi-component `install --all` and `sync --all` planning;
- post-operation project re-discovery and doctor verification;
- human-readable and JSON output.

No GitHub Actions workflows are used. Validation is local and script-driven.

## Run locally

Python 3.11+ is the only requirement for UPM itself.

```sh
sh ./scripts/check.sh
```

Run the CLI without installing it:

```sh
PYTHONPATH=src python3 -m unified_project_manager discover .
PYTHONPATH=src python3 -m unified_project_manager graph .
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
upm why zod .
upm duplicates .
upm doctor .
```

Component keys use `<relative-path>:<ecosystem>`, for example `frontend:node`, `backend:python`, or `engine:rust`.

`upm doctor --strict` exits non-zero for warnings as well as errors. Informational findings, such as dependency version divergence across components, do not reduce the health score.

## Integrity snapshots

`upm snapshot` records SHA-256 digests for the native manifests and lockfiles UPM discovered:

```sh
upm snapshot .
# writes .upm/state.json

upm doctor .
```

The snapshot is **not** a universal dependency lockfile. Native lockfiles remain authoritative. The snapshot only gives UPM a portable baseline for detecting changed, missing, newly discovered, or unreadable project-state files.

## Preview-first package operations

Mutating operations do not execute by default. UPM first prints the exact native command it intends to run:

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

After a successful applied operation, UPM re-discovers the repository and runs its doctor checks unless `--no-verify` is supplied.

For a mixed repository, a single-component operation requires `--component` unless UPM can identify exactly one component. `--all` is intentionally limited to `install` and `sync`; dependency additions/removals remain explicitly component-targeted.

Current delegated managers are:

| Ecosystem | Managers | Examples of delegated operations |
| --- | --- | --- |
| Node | npm, pnpm, Yarn, Bun | install, frozen/immutable sync, add, remove |
| Python | uv, Poetry, PDM | install/sync, add, remove |
| Python requirements | pip | install only; manifest mutation is deliberately refused |
| Rust | Cargo | fetch/locked fetch, add, remove |

UPM blocks planning when manager ownership is ambiguous, such as multiple native lockfiles or a manifest/lockfile manager mismatch.

## Initialize projects

Initialization is also preview-first and delegates to native generators:

```sh
upm init frontend --ecosystem node --manager pnpm
upm init backend --ecosystem python
upm init engine --ecosystem rust --lib
```

Add `--apply` to execute. The current defaults are npm for Node, uv for Python, and Cargo for Rust. Node initialization supports npm, pnpm, and Bun; Python initialization currently supports uv; Rust initialization uses Cargo.

For safety, the target must be new or empty and must remain inside the current project root. UPM does not currently adopt or overwrite an existing project during initialization.

## JSON output

Read commands and command plans have machine-readable forms:

```sh
upm discover --json
upm graph --json
upm doctor --json
upm why react --json
upm duplicates --json
upm snapshot --json
upm sync --all --json
upm init service --ecosystem python --json
```

## Design principles

1. **Native managers remain authoritative.** UPM delegates dependency resolution and mutation rather than reimplementing ecosystem semantics.
2. **Normalize observations, not lockfiles.** Native manifests and lockfiles stay first-class; UPM builds a common project graph above them.
3. **Preview before mutation.** Native commands are visible before execution and require an explicit `--apply`.
4. **Refuse ambiguity.** Conflicting managers, lockfiles, or component selectors are errors instead of guesses.
5. **Leaky abstraction by design.** A common workflow should not erase ecosystem-specific behavior or block native escape hatches.
6. **Local-first health.** Project integrity, drift, duplication, runtime mismatch, and corruption detection are core product features.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the current architecture and milestone status.
