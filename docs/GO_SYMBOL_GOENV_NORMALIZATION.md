# Go symbol GOENV normalization characterization

This is **pre-public design evidence** for the Go vulnerable-symbol promotion gate. It does not create a public provider, persisted symbol evidence, or a freshness claim.

## Why this exists

The candidate source observation and govulncheck executor inherit most of the calling process environment. Go can also read per-user defaults written by `go env -w` from the Go environment configuration file. In particular, persisted `GOFLAGS` can change build tags and therefore package/source selection even when the operating-system `GOFLAGS` variable is empty.

Go documents `GOENV=off` as disabling use of the default Go environment configuration file. UPM now sets `GOENV=off` in **both** pre-public plans, so persisted `go env -w` state is excluded from the candidate observation and scanner subprocess environments.

Process-level `GOFLAGS` is handled separately rather than erased. Each plan captures the process value at plan-construction time, defaulting an absent value to the explicit empty string. Planned build-selection alignment requires the two captured values to agree and requires the value to be empty. This means:

- a non-empty user `GOFLAGS` remains fail-closed;
- a change between observation-plan and scanner-plan construction is visible as plan drift;
- a later process-environment mutation cannot override the already-authorized plan value at execution time;
- the Go-native observation still checks the effective `GOFLAGS` reported by `go env -json` before a real scanner gate may continue.

This closes the persisted-configuration and process-`GOFLAGS` plan/TOCTOU gaps. It does **not** prove complete govulncheck source/build equivalence.

## Characterization

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

## Implemented plan contract

Both pre-public plans now carry:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
GOENV = off
GOFLAGS = captured process value, required empty for planned alignment
```

`GOFLAGS` is included in the exact plan authorization identity because that identity already binds the complete sorted plan environment. The scanner executor therefore cannot silently run a plan whose captured GOFLAGS differs from the preflight-authorized plan.

The local Go 1.23.2 characterization also confirmed that `GOENV=off` does not mask `GOTELEMETRY`; the existing preflight still requires telemetry to already be exactly `off` and never changes it.

## Interpretation boundary

The implemented normalization establishes a narrower plan/executor property only:

```text
persisted_go_env_configuration = disabled
process_GOFLAGS = captured-and-fail-closed
planned_GOFLAGS_alignment = exact-empty-required
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

The next promotion work remains a real govulncheck alignment/side-effect run where `go` and `govulncheck` already exist and telemetry is already exactly `off`, followed by conservative treatment of any other build-environment inputs shown to affect scanner loading. The GOENV/GOFLAGS controls must not be treated as a substitute for that runtime evidence.
