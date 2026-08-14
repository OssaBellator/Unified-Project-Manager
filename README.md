# Unified Project Manager

Unified Project Manager (`upm`) is an experimental package-manager-agnostic control plane for development projects. It does **not** replace npm, pnpm, uv, Cargo, or other native package managers. Instead, it discovers them, normalizes project state, diagnoses inconsistencies, and will eventually delegate mutations back to the native tools.

## Current vertical slice

The first implementation is intentionally read-only. It supports:

- recursive project discovery while skipping install/build directories;
- Node projects (`package.json`, npm/pnpm/yarn/bun lockfiles);
- Python projects (`pyproject.toml`, requirements files, uv/Poetry/PDM lockfiles);
- Rust projects (`Cargo.toml`, `Cargo.lock`);
- normalized direct dependency and toolchain metadata;
- `upm discover`, `upm graph`, and `upm doctor`;
- detection of malformed manifests, conflicting Node lockfiles, manager/lockfile mismatches, missing lockfiles, and unavailable local tools.

No GitHub Actions workflows are used. Validation is local and script-driven.

## Run locally

Python 3.11+ is the only requirement.

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

JSON output is available on the read commands:

```sh
upm discover --json
upm graph --json
upm doctor --json
```

`upm doctor --strict` exits non-zero for warnings as well as errors, which makes it suitable for local hooks or any external CI system without coupling the repository to GitHub Actions.

## Design principles

1. **Native managers remain authoritative.** UPM should delegate dependency resolution and mutation rather than reimplement ecosystem semantics.
2. **Normalize observations, not lockfiles.** Native manifests and lockfiles stay first-class; UPM builds a common project graph above them.
3. **Read before write.** Discovery and health checks come before repair or mutation commands.
4. **Leaky abstraction by design.** A common 80% workflow should not prevent ecosystem-specific escape hatches.
5. **Local-first health.** Project integrity, drift, duplication, runtime mismatch, and corruption detection are core product features.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the current implementation plan.
