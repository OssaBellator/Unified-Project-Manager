# Go symbol source/build observation

This is a **pre-public candidate freshness input**, not a symbol-evidence freshness model.

UPM needs stronger evidence than a `go.mod`/`go.sum` hash before persisted govulncheck symbol results can ever be replayed safely. Source-mode call graphs depend on the actual Go package selection and build environment, so UPM now has a Go-native observation layer that records what the installed Go tool selects under the same offline/single-module guards used by the pre-public symbol provider.

## Observation plan

The plan executes:

```text
go env -json
go list -mod=readonly -deps -json ./...
```

with:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

The observation is deliberately read-only at the project level. Non-project Go cache/tool state may still be touched by the Go tool.

## Build environment retained

UPM keeps resolved Go build inputs such as:

- `GOOS`;
- `GOARCH`;
- `GOVERSION`;
- `CGO_ENABLED`;
- `GOFLAGS`;
- `GOEXPERIMENT`;
- architecture tuning variables when present (`GOAMD64`, `GOARM`, etc.);
- C/C++/pkg-config and CGO flags when reported by `go env`.

Machine-local cache paths such as `GOMODCACHE` are not promoted into the semantic build-environment record merely because `go env -json` reports them.

## Package/source inputs retained

For each package returned by `go list -deps -json`, UPM records:

- import path and package name;
- standard-library versus module package;
- root versus dependency-only state;
- package directory;
- original and effective module path/version, including replacements;
- selected Go/Cgo/C/C++/Objective-C/header/Fortran/assembly/Swig/syso/embed inputs when reported;
- ignored Go/other files separately;
- package imports.

Incomplete packages, package errors, dependency errors, malformed module identity, or malformed file lists fail the observation rather than producing a partial freshness claim.

## Candidate-only semantics

The serialized contract explicitly says:

```text
scope = candidate-govulncheck-source-build-inputs
freshness = not-established
govulncheck_equivalence = not-established
source_state_fingerprint = false
```

The observation is useful because it reflects Go's selected files/build environment instead of blindly hashing every source-like file in the repository. But until it is compared with a real govulncheck source scan, UPM does **not** claim that the two tools select identical packages/files or interpret all build configuration identically.

## Scanner-SBOM alignment

`compare_go_symbol_observation_to_scan_sbom(...)` compares only normalized declarations:

- root package set from the Go-native observation;
- effective non-standard module path/version set from the Go-native observation;
- roots and module build list declared by govulncheck's retained native scan SBOM.

The result exposes independent `roots_match` and `modules_match` fields plus:

```text
declared_inventory_match = roots_match && modules_match
```

Even when true, the result remains:

```text
freshness = not-established
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
```

A module/root inventory match is evidence of agreement at that level only. It does not prove identical source-file selection, build tags, environment, generated inputs, or call graph.

Replacement comparison uses the Go-native observation's **effective** module identity, matching the existing strict govulncheck symbol-correlation contract.

## Real local Go check

The deterministic versioned runtime fixture is reused for source observation. After `example.com/dep@v1.2.3` is populated from the generated local `file://` module proxy, the candidate observation runs with `GOPROXY=off` and isolated `GOMODCACHE`/`GOCACHE`.

A real installed Go 1.23.2 check in this implementation environment successfully:

- selected the app's `main.go`;
- selected the dependency's `dep.go`;
- reported `example.com/dep@v1.2.3`;
- retained resolved Go build environment identity;
- left the prepared `go.mod`, `go.sum`, and `main.go` snapshot unchanged.

This validates the Go-native observation boundary, not govulncheck equivalence.

## Optional real govulncheck alignment

`tests/test_go_symbol_real_alignment.py` is an opt-in regression included through a dedicated local driver:

```sh
sh ./scripts/test-go-symbol-real-alignment.sh
```

It skips unless `go` and `govulncheck` already exist and `GOTELEMETRY` is already `off`. It never installs a tool or changes telemetry.

When runnable it uses the same generated local DB, local module proxy, versioned dependency, app, and isolated caches for both:

1. the Go-native source/build observation;
2. the real pre-public govulncheck scan.

It then requires the two declarations to agree on roots and effective module/version inventory. Passing that future check still does **not** establish a source/build freshness fingerprint; it only validates the alignment assumption needed before designing one.

## Validation drivers

```sh
sh ./scripts/test-go-symbol-source-observation.sh
sh ./scripts/test-go-symbol-source-alignment.sh
sh ./scripts/test-go-symbol-real-alignment.sh
```

The real alignment driver is expected to skip in environments that do not already satisfy govulncheck/telemetry prerequisites.

## Persistence boundary

No persisted symbol freshness state uses this observation yet. A future fingerprint must be derived only after real govulncheck alignment is proven and must conservatively account for any remaining source/build inputs not represented by this Go-native observation.
