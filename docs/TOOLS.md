# Manager and toolchain resolution

Package state is only one part of reproducibility. Two checkouts with identical manifests/lockfiles can behave differently if they resolve different package-manager or language-toolchain executables.

UPM therefore treats executable resolution as observable project context rather than assuming that a command name on `PATH` is a stable identity.

## Local tool inventory

The local inventory reports, per discovered component:

- role: package manager or language toolchain;
- logical tool name;
- declared/required version expression when UPM can observe one;
- version-probe argv;
- exact executable path returned by local resolution;
- availability;
- observed version output;
- version-probe return code;
- version-probe stderr when relevant.

Known probes include npm, pnpm, Yarn, Bun, uv, Poetry, PDM, pip-through-Python, Cargo, Go, Node, Python, and Rust.

The inventory resolves the executable once and invokes that exact path for the local version probe. It does not run a shell.

Repeated identical probes are cached during one inventory operation, so a repository containing several npm components does not execute `npm --version` once per component.

## Requirement divergence

UPM can report when different components declare different requirements for the same manager or toolchain.

Examples:

- one package declares `npm@10`, another `npm@11`;
- one component requires Node `>=20`, another `>=22`.

This is evidence of divergent project requirements. UPM does **not** decide that one declaration is correct or install/switch versions automatically.

## Strict mode

The inventory command can be used in a strict local check. Strict failure conditions are intentionally mechanical:

- requested executable cannot be resolved;
- a version probe fails;
- declared requirements for the same role/tool diverge across components.

Version *compatibility* remains the responsibility of the existing ecosystem-aware doctor/toolchain checks; the inventory does not implement a universal version-expression language.

## Machine-local baseline

`.upm/tools.json` is an optional machine-local baseline for executable resolution.

It stores:

- component/role/tool identity;
- declared requirement;
- exact absolute resolved path;
- availability;
- observed version;
- version-probe return code.

Its `state_id` is deterministic over those observations and excludes the generation timestamp.

The file declares:

```json
{"portable": false}
```

because absolute executable paths are inherently machine-specific.

## Drift classes

Comparing current tool inventory with the baseline can report:

- `tool-path-changed` — exact executable resolution changed;
- `tool-version-changed` — observed version text changed;
- `tool-availability-changed` — tool appeared/disappeared;
- `tool-version-probe-changed` — probe return state changed;
- `tool-requirement-changed` — project declaration changed;
- `tool-observation-added` / `tool-observation-removed` — component/tool identity set changed.

Path drift is reported even when the version string is identical. A same-version executable from a different directory may represent a shim, local override, compromised PATH entry, alternate runtime installation, or simply an intentional environment change; UPM reports the fact and does not guess the cause.

## Preview and writes

Tool inventory itself is read-only/local.

Writing the machine-local baseline is explicit and preview-first. Checking it is read-only.

No manager/toolchain installation or update is performed by the tool inventory/baseline layer.

## Relationship to project integrity snapshots

`.upm/state.json` and `.upm/tools.json` answer different questions:

- project integrity snapshot: did portable native project files change?
- tool baseline: did this machine resolve/use different executables or versions?

They should not be collapsed into one portable lockfile. A project may commit/share the portable project state while keeping machine-local executable paths local to a workstation, development container, or build agent.

## Security boundary

The local baseline is self-validating against its `state_id`, which catches partial edits/corruption. It is not externally authenticated.

A user/attacker who can replace both the baseline and the current tool environment can establish a new local baseline. External trust/signing policy is a separate concern.

## Non-goals

This layer does not:

- install missing tools;
- mutate PATH;
- choose a tool-version manager;
- claim different executable paths are automatically malicious;
- replace ecosystem-specific toolchain compatibility checks;
- make absolute executable paths portable across machines.