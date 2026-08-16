# Go symbol GOENV normalization characterization

This is **pre-public design evidence** for the Go vulnerable-symbol promotion gate. It does not create a public provider, persisted symbol evidence, or a freshness claim.

## Why this exists

The candidate source observation and govulncheck executor intentionally inherit most of the calling process environment. Go can also read per-user defaults written by `go env -w` from the Go environment configuration file. In particular, persisted `GOFLAGS` can change build tags and therefore package/source selection even when the operating-system `GOFLAGS` variable is empty.

Go documents `GOENV=off` as disabling use of the default Go environment configuration file. A normalized `GOENV=off` therefore has a useful property for the promotion gate: persisted `go env -w` state is excluded, while an explicit process-level `GOFLAGS` value remains visible and can still be rejected by the existing fail-closed effective-`GOFLAGS` guard.

This characterization does **not** yet change the scanner or observation plans. It proves the Go-command behavior needed before that normalization is wired into both paths atomically.

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

## Interpretation boundary

A successful result supports this **candidate normalization direction**:

```text
GOENV = off
```

for both the Go-native source observation and real govulncheck subprocess environment. It does not by itself prove the govulncheck path uses identical source/build inputs, because the real scanner must still be executed and compared after the same normalization is wired into both plans.

Even after this characterization succeeds:

```text
ambient_GOFLAGS_equivalence = not-established
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
source_state_fingerprint = false
public = false
persisted = false
```

The next code change should add `GOENV=off` to **both** pre-public plan environments together, retain the effective-`GOFLAGS` blocker for explicit process flags, and rerun the real govulncheck alignment/side-effect gate where prerequisites already exist and telemetry is already exactly `off`.
