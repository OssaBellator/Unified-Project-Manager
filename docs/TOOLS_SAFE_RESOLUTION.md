# Execution-safe manager and toolchain resolution

> **Canonical implementation:** `tool_resolution.py` and `tool_resolution_state.py` supersede the earlier tool-inventory prototype. The earlier prototype executed version commands by default and therefore cannot honestly guarantee zero network behavior when commands resolve through Corepack or another shim/version manager.

Executable resolution is itself useful evidence. Executing an executable to learn its version is a different action with a different trust/network boundary. UPM keeps those two modes separate.

## Default mode: resolve paths, execute nothing

The canonical local tool-resolution operation defaults to:

- discover manager/toolchain identities from project components;
- call local executable lookup only;
- record the exact path that would be executed;
- record declared manager/toolchain requirements where UPM can observe them;
- report availability and cross-component requirement divergence;
- execute **zero** package-manager/toolchain binaries.

In this mode UPM can truthfully report:

```text
version_probes_executed = false
network_guarantee = no-execution
network_executed = false
mutation_executed = false
```

No version is inferred from a path or filename.

## Explicit version-probe mode

Version observation requires explicit opt-in (`--probe-versions`). UPM then executes the exact resolved binary using a manager/toolchain-specific version argv.

For package managers that can be fronted by Corepack, UPM sets:

```text
COREPACK_ENABLE_NETWORK=0
```

for the probe environment. This prevents Corepack itself from downloading a package manager.

That is a **mitigation, not a universal offline guarantee**. The resolved executable can be another shim, wrapper, launcher, or version manager with behavior outside Corepack. Therefore probe mode reports:

```text
version_probes_executed = true
network_guarantee = not-guaranteed
network_executed = null
```

`null` means UPM does not claim to have proven whether the executed local shim/tool performed network I/O.

## Probe commands

Known manager probes include:

- npm: `npm --version`
- pnpm: `pnpm --version`
- Yarn: `yarn --version`
- Bun: `bun --version`
- uv: `uv --version`
- Poetry: `poetry --version`
- PDM: `pdm --version`
- pip: `python -m pip --version`
- Cargo: `cargo --version`
- Go: `go version`

Known toolchain probes include Node, Python, Rust/rustc, and Go.

The logical command is retained for display, while execution uses the exact path returned by local resolution. Repeated identical exact probes are cached within one collection.

## Requirement divergence

Requirement comparison is available in both modes and executes nothing by itself.

Examples:

- two components declare `npm@10` and `npm@11`;
- two components require different Node version expressions.

This is an observation, not universal compatibility solving. Ecosystem-specific doctor/toolchain logic remains responsible for interpreting supported version expressions.

## Machine-local baseline v2

The canonical `.upm/tools.json` schema is version 2.

The state ID binds:

- schema version;
- `portable=false`;
- whether version probes were executed;
- component/role/tool identity;
- declared requirement;
- exact resolved path;
- availability;
- version and probe return code **only when probe mode was explicitly used**.

The generation timestamp is display metadata and is excluded from stable state identity.

### Path-only baseline

A baseline created without probes contains no version/probe evidence. Later checks resolve paths only and execute no manager/toolchain binaries.

A path-only baseline can detect:

- requirement changes;
- exact executable path changes (including PATH shadowing);
- availability changes;
- added/removed component/tool observations.

It cannot claim version drift because no version was observed.

### Probe-enabled baseline

A baseline created with `--probe-versions` binds version/probe results.

A later ordinary check **does not silently run probes**. It returns `probe-required` and performs zero tool execution until the caller supplies `--probe-versions` again.

A path-only baseline checked with `--probe-versions` is rejected as a mode mismatch. The user must explicitly resnapshot in probe mode first. This prevents a check operation from silently widening the evidence class.

### Prototype v1 baselines

The earlier prototype `.upm/tools.json` version 1 is rejected by the canonical v2 reader with resnapshot guidance. It is not silently upgraded because its execution/network semantics were weaker than the v2 contract.

## Drift categories

For path-only baselines:

- `tool-requirement-changed`
- `tool-path-changed`
- `tool-availability-changed`
- `tool-observation-added`
- `tool-observation-removed`

Probe-enabled baselines additionally compare:

- `tool-version-changed`
- `tool-version-probe-changed`

A path change is meaningful even when a probed version string remains identical: a new shim/local override/executable location is separate evidence from the version it reports.

## Privacy and portability

Absolute executable paths are machine-specific, so the baseline explicitly declares `portable=false`.

This file should be treated as local agent/workstation/container evidence rather than a portable replacement for project lockfiles or `.upm/state.json`.

## Non-goals

This layer does not:

- install or switch package managers/toolchains;
- mutate `PATH`;
- guarantee that arbitrary third-party shims are offline when executed;
- infer versions without explicit execution;
- treat a different executable path as automatically malicious;
- replace native toolchain compatibility/version rules;
- make machine-local executable paths portable.
