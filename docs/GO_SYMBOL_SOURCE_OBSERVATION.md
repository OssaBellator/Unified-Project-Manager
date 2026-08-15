# Go symbol source/build observation

This is a **pre-public candidate freshness input**, not a symbol-evidence freshness model.

UPM needs stronger evidence than a `go.mod`/`go.sum` hash before persisted govulncheck symbol results can ever be replayed safely. Source-mode call graphs depend on the actual Go package selection and build environment, so UPM now has a Go-native observation layer that records what the installed Go tool selects under the same offline/single-module guards used by the pre-public symbol provider.

## Observation plan

The plan executes:

```text
go env -json
go list -mod=readonly -deps -compiled -json ./...
```

with:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

The observation is deliberately read-only at the project level. Non-project Go cache/tool state may still be touched by the Go tool.

## Why `-compiled` matters

Govulncheck source-symbol analysis loads packages through `golang.org/x/tools/go/packages` with syntax/type information. The Go packages loader defines `Syntax` as syntax trees for `CompiledGoFiles`, and its Go-command driver requests compiled file information when syntax/types are needed.

UPM therefore keeps two source views separate:

```text
selected_files    = broader Go/Cgo/C/C++/assembly/embed build inputs
syntax_go_files   = CompiledGoFiles reported as suitable for type checking
```

Those sets may differ. In particular, cgo processing can produce compiled Go inputs that are not the same paths as the raw Cgo/Go source list.

UPM does **not** hash `CompiledGoFiles` as a freshness claim yet. Generated/cache paths can appear there, and real govulncheck alignment remains a promotion gate.

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

`GOFLAGS` is retained because it can affect the Go command's effective build configuration. The separate build-selection guard currently validates the explicit scanner/observation package-pattern, build-tag, and test-selection arguments; resolved ambient build configuration still remains candidate evidence rather than runtime-equivalence proof.

## Package/source inputs retained

For each package returned by `go list -deps -compiled -json`, UPM records:

- import path and package name;
- standard-library versus module package;
- root versus dependency-only state;
- package directory;
- original and effective module path/version, including replacements;
- raw selected Go/Cgo/C/C++/Objective-C/header/Fortran/assembly/Swig/syso/embed inputs when reported;
- `CompiledGoFiles` separately as `syntax_go_files`;
- ignored Go/other files separately;
- package imports.

Pseudo-packages such as `unsafe` may legitimately have no `CompiledGoFiles`; absence is retained rather than fabricated. Incomplete packages, package errors, dependency errors, malformed module identity, or malformed file lists fail the observation rather than producing a partial freshness claim.

## Planned build-selection guard

`compare_go_symbol_build_selection(...)` compares the scanner and observation command plans before the optional real-runtime tests are allowed to launch govulncheck.

The current accepted candidate is:

```text
patterns = ["./..."]
tags = []
tests = false
```

Package-pattern or build-tag drift is explicit. Test-enabled selection remains fail-closed even when both command lines request tests, because UPM has not yet proven equivalence between govulncheck's `go/packages` test loading and `go list -test` package variants.

See `GO_SYMBOL_BUILD_SELECTION.md`.

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

## Real local Go checks

The deterministic versioned runtime fixture is reused for source observation. After `example.com/dep@v1.2.3` is populated from the generated local `file://` module proxy, the candidate observation runs with `GOPROXY=off` and isolated `GOMODCACHE`/`GOCACHE`.

The existing real fixture check validates that the app and dependency sources are selected, the expected module/version is reported, and the prepared project snapshot is unchanged.

A separate live Go sanity check for the compiled-input change also confirmed:

```text
GoFiles          = [main.go]
CompiledGoFiles  = [main.go]
IgnoredGoFiles   = [windows_only.go]
project snapshot = unchanged
```

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

Before launching the scanner it now also requires the planned build-selection guard to pass. It then requires the two declarations to agree on roots and effective module/version inventory.

Passing that future check still does **not** establish a source/build freshness fingerprint; it only validates the alignment assumptions needed before designing one.

## Validation drivers

```sh
sh ./scripts/test-go-symbol-build-selection.sh
sh ./scripts/test-go-symbol-source-observation.sh
sh ./scripts/test-go-symbol-source-alignment.sh
sh ./scripts/test-go-symbol-real-alignment.sh
sh ./scripts/test-go-symbol-prepublic-all.sh
```

The real alignment driver is expected to skip in environments that do not already satisfy govulncheck/telemetry prerequisites.

## Persistence boundary

No persisted symbol freshness state uses this observation yet. A future fingerprint must be derived only after real govulncheck alignment is proven and must conservatively account for any remaining source/build inputs not represented by this Go-native observation.
