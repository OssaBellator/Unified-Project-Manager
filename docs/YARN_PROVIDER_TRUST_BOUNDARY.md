# Yarn Berry provider trust boundary

UPM's Yarn Berry provider is designed as an offline, project-state-preserving native query. That statement describes the command UPM plans and the Berry configuration UPM supplies; it is **not a sandbox guarantee for arbitrary third-party Yarn plugin code**.

## What UPM controls

For the public Berry relationship provider UPM:

- requires an explicitly declared Yarn 2+ project with `yarn.lock`;
- verifies the resolved runtime reports Yarn 2 or newer;
- runs the native `yarn info` machine-readable relationship surface;
- forces Berry network access off;
- redirects install-state persistence to a temporary path outside the project;
- makes Yarn cache mutation immutable;
- suppresses telemetry;
- does not request archive/cache/manifest extras that would intentionally fetch package contents;
- removes the temporary install-state directory after the query.

These controls are why the provider is classified as **offline** rather than as a static/no-execution provider.

## What UPM does not sandbox

A Yarn project can load plugins. Plugins are executable code inside the Yarn process. The `info` command exposes package-info extension hooks, so a malicious or nonconforming plugin is outside the guarantees that can be established merely by choosing safe built-in CLI flags.

UPM currently does not provide an OS-level sandbox for package-manager processes or plugin code. Consequently:

- `enableNetwork=false` is a Berry configuration guarantee, not a kernel-level network namespace;
- temporary `installStatePath` prevents Berry's normal install-state write, but cannot mathematically prevent arbitrary plugin code from opening another project file;
- immutable-cache configuration prevents supported Yarn cache writes, but is not a filesystem sandbox;
- an external runtime bootstrap/dispatch shim is also outside Berry's own configuration boundary.

This is the same general trust boundary UPM should state for any native package manager that can load executable plugins/extensions.

## Review implication

Provider capability metadata such as `offline`, `project-read-only`, or `mutation: none` should be interpreted as **the intended/native command contract**, not as proof that arbitrary extension code is sandboxed.

A future stronger isolation mode would need process-level controls such as filesystem and network sandboxing, plus a policy for whether project-defined package-manager plugins are permitted. That is a separate feature from relationship normalization and should not be implied by the current provider labels.

## Current compatibility cleanup

`yarn_graph.py` still sets a hardened-mode configuration override that is not needed for the safety model. The preferred cleanup remains:

1. remove that override;
2. keep Berry network refusal, temporary install state, immutable cache, and telemetry suppression;
3. fail explicitly if an older/runtime-specific Berry cannot reconstruct its graph under those constraints;
4. update the focused Yarn execution test and provider documentation together.

Until the existing file can be safely edited through the repository connector, this remains a narrow compatibility cleanup rather than a reason to weaken the fail-closed provider behavior.
