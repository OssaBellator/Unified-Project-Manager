# Go symbol GO111MODULE characterization

This is **pre-public design evidence** for the Go vulnerable-symbol promotion gate. It does not create a public provider, persisted symbol evidence, or a freshness claim.

## Why this exists

The candidate source observation is explicitly a single-module `go list -mod=readonly ... ./...` profile, and govulncheck source mode also relies on module-aware package loading. `GO111MODULE=off` can force the Go command out of module-aware mode, which is incompatible with that candidate contract even when `go.mod` is present.

The safest eventual normalization is therefore stronger than merely comparing an inherited value: both pre-public plans should explicitly require module-aware mode.

## Characterization

Run either:

```sh
sh ./scripts/characterize-go-symbol-go111module.sh
```

or:

```powershell
./scripts/characterize-go-symbol-go111module.ps1
```

The driver requires an already-installed Go 1.21+ executable, creates only a temporary one-module fixture, and runs `go env GO111MODULE` plus `go list -mod=readonly -json .` under:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
GOENV = off
GOFLAGS = ""
GOROOT = ""
```

It characterizes `GO111MODULE` when unset, explicitly empty, `auto`, `on`, and `off`.

The local Go 1.23.2 run established:

```text
unset -> readonly module list succeeds
empty -> readonly module list succeeds
auto  -> readonly module list succeeds
on    -> readonly module list succeeds
off   -> fails: -mod=readonly is only valid when using modules
```

The command never writes `go env -w`, never installs Go, never changes telemetry, and does not mutate a real project. Unavailable/too-old Go is `status = blocked` / exit 2; a behavioral mismatch is `status = failed` / exit 1. Blocked is not a pass.

## Interpretation boundary

This supports an eventual normalized plan input:

```text
GO111MODULE = on
```

for both the source-observation and govulncheck plans, because the pre-public stack is intentionally module-aware and single-module. It should be included in planned environment comparison and exact plan authorization when promoted.

Until that atomic production change is made:

```text
planned_GO111MODULE_normalization = not-implemented
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
source_state_fingerprint = false
public = false
persisted = false
```

A successful characterization is not a substitute for the real govulncheck alignment/side-effect gate.
