# Go symbol source/build observation

This is a **pre-public candidate freshness input**, not a symbol-evidence freshness model.

UPM needs stronger evidence than a `go.mod`/`go.sum` hash before persisted govulncheck symbol results can ever be replayed safely. Source-mode call graphs depend on actual package selection and build environment, so UPM records a Go-native candidate observation under the same offline/single-module guards as the pre-public symbol provider.

## Normalized loader profile

For this candidate, UPM now requires **Go 1.21+** and executes:

```text
go env -json
go list -e -mod=readonly -deps=true -compiled=true -test=false \
  -export=false -find=false -buildvcs=false -pgo=off -json -- ./...
```

with:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

The Go 1.21 floor applies only to this **pre-public candidate freshness observation**, not to the eight public relationship providers or public Go import reachability. If the observed `GOVERSION` is older than 1.21 or cannot be interpreted, UPM refuses the candidate observation before package loading.

The profile intentionally mirrors the current x/tools `go/packages` Go-list driver where that is semantically useful: error-tolerant package records, compiled syntax inputs, dependency loading, tests off, export/find off, VCS stamping off, and automatic PGO off. Current govulncheck v1.6.0 declares Go 1.25.0 and x/tools v0.48.0; this environment has only validated the observation command itself with Go 1.23.2. Real govulncheck alignment therefore remains required.

The observation is read-only at the project level by design. Non-project Go cache/tool state may still be touched.

## Compiled syntax inputs versus broader build inputs

Govulncheck source-symbol analysis loads packages through `golang.org/x/tools/go/packages` with syntax/type information. The packages loader defines its syntax trees from `CompiledGoFiles`, so UPM keeps two views separate:

```text
selected_files    = broader Go/Cgo/C/C++/assembly/embed build inputs
syntax_go_files   = CompiledGoFiles reported as suitable for type checking
```

Those sets may differ. In particular, cgo processing may create compiled Go inputs that do not correspond one-for-one with raw source paths. UPM does **not** hash generated/cache paths as freshness evidence yet.

## Build environment retained

UPM retains resolved build inputs including `GOOS`, `GOARCH`, `GOVERSION`, `CGO_ENABLED`, `GOFLAGS`, `GOEXPERIMENT`, architecture tuning variables, compiler/pkg-config identity, and CGO flags when reported.

Machine-local cache paths such as `GOMODCACHE` are not promoted into the semantic build-environment record merely because `go env -json` reports them.

Explicit command flags normalize VCS stamping and PGO for the candidate observation. Ambient configuration such as `GOFLAGS` is still recorded because it can affect Go behavior; a real scanner run remains necessary before UPM can claim complete loader equivalence.

## Package/source inputs retained

For each package UPM records:

- import path and package name;
- standard-library versus module package;
- root versus dependency-only state;
- package directory;
- original and effective module path/version, including replacements;
- selected Go/Cgo/C/C++/Objective-C/header/Fortran/assembly/Swig/syso/embed inputs;
- `CompiledGoFiles` separately as `syntax_go_files`;
- ignored Go/other files;
- imports.

Pseudo-packages such as `unsafe` may legitimately have no `CompiledGoFiles`; absence is retained rather than fabricated. Incomplete packages, package errors, dependency errors, malformed module identity, or malformed file lists fail closed.

## Planned build-selection guard

`compare_go_symbol_build_selection(...)` compares scanner and observation command plans before optional real-runtime tests may launch govulncheck.

The current accepted candidate is:

```text
patterns = ["./..."]
tags = []
tests = false
```

Pattern or tag drift is explicit. Test-enabled selection remains fail-closed even if both plans request tests, because UPM has not proven equivalence between govulncheck's `go/packages` test loading and `go list -test` package variants.

See `GO_SYMBOL_BUILD_SELECTION.md`.

## Candidate-only semantics

```text
scope = candidate-govulncheck-source-build-inputs
freshness = not-established
govulncheck_equivalence = not-established
source_state_fingerprint = false
```

This observation is intentionally more precise than blindly hashing every source-like file, but it is still candidate evidence. UPM does **not** claim identical package/source/type loading or call graphs until compared with real govulncheck output.

## Scanner-SBOM alignment

`compare_go_symbol_observation_to_scan_sbom(...)` compares only normalized root packages and effective non-standard module/version inventory against govulncheck's retained native scan SBOM.

Even when both match:

```text
declared_inventory_match = true
freshness = not-established
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
```

Replacement comparison uses effective module identity, matching strict symbol correlation.

## Positioned finding-frame/source correspondence

`compare_positioned_govulncheck_frame_to_source_observation(...)` adds a narrower fail-closed check for one reported govulncheck frame that contains a source position. It requires exact observed package identity plus effective module/version agreement, then resolves govulncheck's module-relative `Position.Filename` against the observed package's `CompiledGoFiles`/`syntax_go_files`.

The comparison normalizes `/` and `\\` separators, rejects absolute scanner filenames and `..` traversal, accepts absolute `CompiledGoFiles` only when they remain inside the observed package directory, and refuses generated/cache absolute syntax paths outside that directory. Replacement packages use effective module identity for scanner agreement while retaining the logical module namespace when deriving the package-relative path. Standard-library frames and ambiguous package/file candidates remain fail-closed.

A successful result still reports:

```text
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
runtime_reachability = not-evaluated
exploitability = not-established
public = false
persisted = false
```

This is evidence only that a particular positioned scanner frame corresponds to an observed package/syntax file. It does not prove complete `go/packages` versus `go list` source selection or call-graph freshness.

## Current-source numeric byte-position consistency

`validate_positioned_govulncheck_frame_source_location(...)` is an additional narrower witness after filename/source correspondence. It streams only the already-matched syntax-file prefix through govulncheck's zero-based byte offset and compares its 1-based line/byte-column to current source bytes. Unknown column zero cannot support an exact byte-column witness. Possible Go line-directive markers before the scanner position fail closed because adjusted token line/column values need not equal raw source coordinates; markers strictly after the position do not retroactively block it.

The read is guarded against path escape, non-regular/symlink/reparse files, parent/leaf path replacement, and observable file metadata/content changes during the read. Path-stat/open-handle comparisons use identity, size, and mtime, while ctime is compared only within repeated path-stat or repeated handle-stat observations so Windows cross-interface ctime representation does not create a false mutation. A successful result is still point-in-time single-file evidence only:

```text
freshness = not-established
call_graph_freshness = not-established
source_state_fingerprint = false
symbol_text_correspondence = not-established
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
public = false
persisted = false
```

Reading source may update access-time metadata depending on filesystem policy. Current content-tree side-effect snapshots cover path, size, and SHA-256 rather than atime/ctime/permissions.

## Real local Go evidence

On the generated fully local fixture, the installed Go tool already proved offline package/source observation and project-state immutability.

The exact normalized loader command was also exercised with Go 1.23.2 in a temporary module containing a Windows-only build-tagged file:

```text
env exit          = 0
list exit         = 0
GoFiles           = [main.go]
CompiledGoFiles   = [main.go]
IgnoredGoFiles    = [windows_only.go]
project snapshot  = unchanged
```

This proves the candidate command is locally executable on Go 1.23.2. It does **not** prove govulncheck v1.6.0 runtime equivalence.

## Optional real govulncheck alignment

`tests/test_go_symbol_real_alignment.py` skips unless `go` and `govulncheck` already exist and `GOTELEMETRY` is already `off`. It never installs a tool or changes telemetry.

When runnable it uses the same generated local DB, versioned module proxy, app, and isolated caches for both the Go-native observation and real govulncheck. Before launching the scanner it requires planned build-selection alignment; afterwards it requires root/module declaration alignment, requires the synthetic vulnerable `Danger` frame's positioned source to correspond to the observed dependency package/syntax file, and requires the frame's numeric byte position to agree with the current matched source bytes.

Passing that future check still does not establish complete source-selection equivalence and does not by itself create a persisted freshness fingerprint.

## Validation drivers

```sh
sh ./scripts/test-go-symbol-build-selection.sh
sh ./scripts/test-go-symbol-source-observation.sh
sh ./scripts/test-go-symbol-source-alignment.sh
sh ./scripts/test-go-symbol-frame-source-alignment.sh
sh ./scripts/test-go-symbol-frame-source-location.sh
sh ./scripts/test-go-symbol-real-alignment.sh
sh ./scripts/test-go-symbol-prepublic-all.sh
```

## Persistence boundary

No persisted symbol freshness state uses this observation. A future fingerprint must wait for real scanner alignment and must conservatively cover any remaining source/build inputs shown to affect govulncheck analysis.
