# Go symbol build-environment default characterization

This is **pre-public design evidence** for the Go vulnerable-symbol promotion gate. It does not create a public provider, persisted symbol evidence, a source/build fingerprint, or a freshness claim.

## Purpose

`GOENV=off` removes persisted `go env -w` configuration. The current plans also capture/fail-close process `GOFLAGS` and `GOROOT`. Other process-level Go build inputs can still affect package/source selection or compilation behavior, including target OS/architecture, CGO mode, architecture tuning, experiments, compiler selection, and CGO flags.

Before UPM considers freezing a broader set of those values into scanner/observation execution, it needs to know whether an **explicit empty process value** behaves like the variable being absent. That distinction matters because an execution plan can override later ambient mutations only if the plan has an explicit value for the key.

## Command

Run either:

```sh
sh ./scripts/characterize-go-symbol-build-env-defaults.sh
```

or:

```powershell
./scripts/characterize-go-symbol-build-env-defaults.ps1
```

The driver requires an already-installed Go 1.21+ executable and runs only `go version` / `go env` under:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
GOENV = off
```

It removes each retained process build key to obtain the baseline `go env -json` resolution, then sets that one key to the explicit empty string and requires `go env <KEY>` to resolve to the same value.

The retained keys characterized are:

```text
GOOS GOARCH GOROOT CGO_ENABLED GOFLAGS GOEXPERIMENT
GOAMD64 GOARM64 GOARM GO386 GOMIPS GOMIPS64 GOPPC64 GORISCV64 GOWASM
CC CXX PKG_CONFIG
CGO_CFLAGS CGO_CPPFLAGS CGO_CXXFLAGS CGO_FFLAGS CGO_LDFLAGS
```

The local Go 1.23.2 run passed **23/23** retained keys. GOROOT is now additionally controlled by the production plans: each plan captures the process value, planned alignment requires it to be empty, and the source observation retains the effective `go env` GOROOT. The remaining compiler/CGO/target inputs are still characterization-only.

The command never runs `go env -w`, never installs Go, never changes telemetry, and does not mutate a project. Unavailable/too-old Go is `status = blocked` / exit 2; a mismatch is `status = failed` / exit 1. Blocked is not a pass.

## Interpretation boundary

Success establishes only this narrow Go-command behavior for the tested Go version and platform:

```text
explicit-empty retained process build input == unset/default go-env resolution
```

It does **not** establish that UPM should serialize all of these raw values into a plan. Some compiler/CGO values may contain machine-local paths or other user-specific data, so broader plan capture requires an explicit disclosure/redaction decision as well as runtime scanner alignment.

Even after this characterization passes:

```text
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
source_state_fingerprint = false
public = false
persisted = false
```

The next safe design step is to decide which additional build inputs must be frozen or compared for the real scanner gate, while keeping machine-local/sensitive values out of public or persisted representations unless they are strictly required and safely represented.
