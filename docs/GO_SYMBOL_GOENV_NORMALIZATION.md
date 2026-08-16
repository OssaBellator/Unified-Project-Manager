# Go symbol environment normalization characterization

This is **pre-public design evidence** for the Go vulnerable-symbol promotion gate. It does not create a public provider, persisted symbol evidence, or a freshness claim.

## Why this exists

The candidate source observation and govulncheck executor inherit most of the calling process environment. Go can also read per-user defaults written by `go env -w` from the Go environment configuration file. Persisted or process-level build inputs can change package/source selection even when the command-line package patterns are identical.

Go documents `GOENV=off` as disabling use of the default Go environment configuration file. UPM now sets `GOENV=off` in **both** pre-public plans, so persisted `go env -w` state is excluded from the candidate observation and scanner subprocess environments.

Process-level `GOFLAGS` is handled separately rather than erased. Each plan captures the process value at plan-construction time, defaulting an absent value to the explicit empty string. Planned build-selection alignment requires the two captured values to agree and requires the value to be empty. This means:

- a non-empty user `GOFLAGS` remains fail-closed;
- a change between observation-plan and scanner-plan construction is visible as plan drift;
- a later process-environment mutation cannot override the already-authorized plan value at execution time;
- the Go-native observation still checks the effective `GOFLAGS` reported by `go env -json` before a real scanner gate may continue.

`GOROOT` is treated with the same captured-but-required-empty policy. An empty process `GOROOT` lets the selected Go executable use its own configured root. A non-empty custom root is not silently discarded: it is captured in the plan and causes planned alignment to fail closed. The source observation also retains the effective `GOROOT` reported by `go env -json` as semantic build/toolchain context.

This closes the persisted-configuration, process-`GOFLAGS`, and custom-`GOROOT` plan/TOCTOU gaps. It does **not** prove complete govulncheck source/build equivalence.

## GOENV characterization

Run either:

```sh
sh ./scripts/characterize-go-symbol-goenv.sh
```

or:

```powershell
./scripts/characterize-go-symbol-goenv.ps1
```

The driver:

1. requires an already-installed Go 1.21+ executable;
2. creates a temporary module with one ordinary Go file and one `//go:build ambient` file;
3. points `GOENV` at a temporary file and uses `go env -w` only against that isolated file;
4. writes `GOFLAGS=-tags=ambient` to the isolated Go configuration;
5. proves the persisted value affects `go env GOFLAGS` and `go list` source selection;
6. proves `GOENV=off` with empty process `GOFLAGS` ignores the persisted value and excludes the ambient-tagged file;
7. proves explicit process `GOFLAGS=-tags=ambient` still takes effect with `GOENV=off`;
8. deletes the entire temporary directory on exit.

The command never installs Go, never changes telemetry, never writes the user's real Go environment configuration, and runs package selection with `GOPROXY=off`, `GOWORK=off`, `GOSUMDB=off`, and `GOTOOLCHAIN=local`.

Unavailable or too-old Go returns `status = blocked` / exit 2. A behavioral mismatch returns `status = failed` / exit 1. Blocked is not a pass.

## Build-environment default characterization

`scripts/characterize-go-symbol-build-env-defaults.sh` and its PowerShell equivalent separately characterize whether explicitly empty process values reproduce the unset/default `go env` resolution for the retained build-input keys under `GOENV=off`.

The local Go 1.23.2 run passed **23/23** retained keys, including GOROOT. That is design evidence for a possible broader future freeze; it is deliberately **not** a decision to serialize arbitrary compiler, pkg-config, or CGO values into plans because those values may contain machine-local or user-specific paths/data.

A separate local Go 1.23.2 GOROOT check established:

```text
GOROOT unset  -> /usr/local/go
GOROOT=""     -> /usr/local/go
```

and `go list fmt` resolved under `/usr/local/go/src/fmt`. An invalid non-empty custom GOROOT failed rather than falling back. The production gate therefore requires planned GOROOT to be empty instead of silently overriding a custom root.

## Implemented plan contract

Both pre-public plans now carry:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
GOENV = off
GOFLAGS = captured process value, required empty for planned alignment
GOROOT = captured process value, required empty for planned alignment
```

`GOFLAGS` and `GOROOT` are included in the exact plan authorization identity because that identity already binds the complete sorted plan environment. The scanner executor therefore cannot silently run a plan whose captured values differ from the preflight-authorized plan.

The local Go 1.23.2 characterization also confirmed that `GOENV=off` does not mask `GOTELEMETRY`; the existing preflight still requires telemetry to already be exactly `off` and never changes it.

## Interpretation boundary

The implemented normalization establishes narrower plan/executor properties only:

```text
persisted_go_env_configuration = disabled
process_GOFLAGS = captured-and-fail-closed
planned_GOFLAGS_alignment = exact-empty-required
process_GOROOT = captured-and-fail-closed
planned_GOROOT_alignment = exact-empty-required
```

It still does not establish:

```text
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
source_state_fingerprint = false
public = false
persisted = false
```

The next promotion work remains a real govulncheck alignment/side-effect run where `go` and `govulncheck` already exist and telemetry is already exactly `off`, followed by conservative treatment of the remaining build-environment inputs shown to affect scanner loading. The GOENV/GOFLAGS/GOROOT controls must not be treated as a substitute for that runtime evidence.
