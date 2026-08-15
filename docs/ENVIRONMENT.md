# Environment leakage inspection

UPM treats process environment as another possible source of project drift, but it does not dump the complete environment or assume every global/shared path is a problem.

The inspection layer is deliberately narrow: only known path-like variables that materially affect supported package/module/import resolution are considered.

## Python

When Python components are present, UPM can observe:

- `VIRTUAL_ENV`;
- `CONDA_PREFIX`;
- `PYTHONPATH` entries.

A virtual/Conda environment outside the selected project is a warning because Python commands may observe installed state unrelated to a project-local environment.

An external `PYTHONPATH` entry is a warning because imports may resolve from source trees outside the selected project.

A project-local `.venv` remains an observation without a leakage warning.

## Node

When Node components are present, UPM can observe `NODE_PATH` entries.

Entries outside the project are warnings because Node module resolution may see external modules that are not represented by the project manager's local install state.

UPM does not read arbitrary npm environment/config variables through this inspection path.

## Go

When Go components are present, an explicit `GOWORK` path is observed.

A `GOWORK` file outside the selected project is a warning because generic Go commands may see a different workspace/module set from the project UPM discovered.

`GOWORK=off` and `GOWORK=auto` are recorded as modes, not leakage warnings.

Component-scoped UPM Go operations already disable ambient workspace inheritance; explicit UPM Go-workspace commands bind to the selected workspace instead.

## Shared homes and caches

The following may be observed as useful context:

- `GOMODCACHE`;
- `GOPATH`;
- `CARGO_HOME`;
- `npm_config_prefix`.

They are **not** classified as project leakage merely because they live outside the repository. Shared caches/tool homes are normal native-tool behavior and are handled by separate cache/storage/provenance layers.

## Privacy boundary

The inspection does not enumerate the process environment.

Only the supported variable names above are read/emitted. A random environment variable containing an API key, credential, or unrelated filesystem path is not surfaced by this command.

The supported values can themselves contain absolute local paths. Output should therefore be treated as machine-local diagnostic data, not automatically published telemetry.

## Relative paths

Relative path entries are inherently contextual because their interpretation depends on the working directory of the tool/process that consumes them.

UPM reports the observed value/path relationship for diagnostic use but does not claim a relative override is portable project state. The safest reproducible configuration is an explicit project-local environment/import path managed by the native ecosystem/tooling.

## Strict mode

Strict mode turns leakage warnings into a non-zero command result. It does not mutate the environment, deactivate a virtualenv, rewrite `PYTHONPATH`/`NODE_PATH`, or alter Go workspace configuration.

## Non-goals

Environment inspection does not:

- dump arbitrary environment variables;
- redact-and-store the entire environment;
- mutate the user's shell/session;
- decide that every external shared tool/cache directory is a leak;
- replace installed-state or PATH/tool-resolution checks;
- infer that an external path is malicious.

It reports the narrow set of environment conditions that can make native project resolution observe state outside the selected project.