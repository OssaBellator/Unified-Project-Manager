# Native provider execution trust

UPM normalizes evidence from both static project state and executable native tools. Those are different trust classes and should not be described as if they provided the same isolation guarantees.

## Static providers

A static provider reads repository files directly through UPM code without invoking the ecosystem tool. Examples include the current uv relationship parser and the lower-level Poetry/PDM lock-provider slice.

For these providers UPM can make strong statements about the operation it performs itself:

- no package-manager process is launched;
- no package-manager plugin/extension code is loaded;
- no native package-manager network client runs;
- the parser does not intentionally mutate the project;
- ambiguity can be retained as data rather than delegated to another process.

This still does not create a complete host sandbox around the Python process, but the provider's behavior is substantially more constrained than native command execution.

## Executed native providers

Go, npm, pnpm, Yarn Berry, and Cargo relationship providers invoke native executables because those tools carry authoritative resolver/workspace semantics that UPM should not reimplement heuristically.

UPM can constrain the **planned command** with mechanisms such as:

- locked/frozen/lockfile-only flags;
- offline or network-disabled configuration;
- explicit working directories;
- argv-only subprocess execution;
- temporary state redirection;
- immutable cache configuration;
- environment isolation for ambient workspace state.

Those controls justify labels such as `offline` or `project-read-only` for the intended native command.

They are not equivalent to an operating-system sandbox.

A native executable may load project-defined extensions, plugins, configuration hooks, wrappers, credential helpers, or other code. An external package-manager bootstrap shim may also run before the package manager's own configuration is active. UPM currently does not put these processes in a filesystem namespace, seccomp profile, network namespace, container, or equivalent host-enforced sandbox.

Therefore capability metadata must be read as:

> the native command UPM requests is designed to have this network/mutation behavior under the package manager's normal semantics.

It must **not** be read as:

> arbitrary code loaded by that process is cryptographically or kernel-level prevented from doing anything else.

## Capability vocabulary

The existing provider fields remain useful, but reviewers should apply these meanings:

- `network = none`: UPM's provider path does not intentionally need network and may be static or use a command whose selected mode does not consult network under normal semantics;
- `network = offline`: UPM actively asks the native tool to refuse/fail rather than use network;
- `mutation = none`: UPM does not intentionally request project mutation and, where applicable, redirects known writable state; this is not a sandbox assertion about arbitrary extension code;
- `mutation = project-read-only`: the native query is intended to leave project manifests/lockfiles unchanged, but may read native caches/state or use tool-managed state outside the project.

A future schema should consider separating **command semantics** from **execution isolation**, for example:

- provider kind: `static` / `native-exec`;
- network contract: `none` / `offline` / `may-use-network`;
- project mutation contract: `none` / `read-only` / `may-mutate`;
- extension trust: `no-native-extensions` / `native-extensions-possible`;
- sandbox: `none` / explicit host-enforced sandbox mode.

That would prevent one field from carrying two different meanings.

## Security/advisory implication

`audit --native` inherits the same distinction. Provider inventory should remain local/offline according to each provider's command contract, but OSV-Scanner is explicitly network-capable. A native provider that fails its requested offline/locked mode should surface an inventory failure instead of silently relaxing the contract.

Persisted advisory evidence proves which exact SBOM was scanned; it does not prove the native provider process was executed inside an OS-level sandbox.

## Design direction

Do not block useful native-provider integration on a future sandbox feature, but do not overclaim isolation either. If UPM later supports hostile-project analysis, add an explicit sandboxed execution mode rather than quietly changing the meaning of existing `offline`/`read-only` labels.
