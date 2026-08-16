# Go symbol build-selection guard

This document describes another **pre-public** trust boundary for Go vulnerable-symbol analysis. It does not create a public provider, CLI flag, persisted freshness record, or execution path.

## Why this exists

Govulncheck source mode loads the user-supplied package patterns through `golang.org/x/tools/go/packages`. Its source loader can vary package selection using:

- package patterns;
- build tags;
- test inclusion.

UPM's candidate source/build observation uses `go list` to observe Go-selected package/source inputs. If those package-selection knobs drift between the govulncheck plan and the observation plan, any later comparison is meaningless even before source-file freshness is considered.

## Current supported candidate

The current UPM pre-public command lines both declare:

```text
patterns = ["./..."]
tags = []
tests = false
```

`compare_go_symbol_build_selection(...)` parses both planned command lines and requires package patterns and build tags to agree.

Build-tag ordering is normalized because the tag set, not comma-list ordering, controls selection.

## Ambient `GOFLAGS` remains a promotion blocker

The current comparator is deliberately a **command-line plan** comparison. It does not yet prove that the effective child-Go configuration is the same when `GOFLAGS` is inherited from the process environment or from values saved by `go env -w`.

This matters because `GOFLAGS` can supply default Go command flags, including build tags. An empty operating-system `GOFLAGS` is not a sufficient normalization strategy: the Go command may then use a persisted `go env -w GOFLAGS=...` value. UPM therefore must not treat the current `tags = []` plan result as proof that no ambient build tags affected a real scanner run.

A local Go 1.23.2 experiment showed that a non-empty process value such as:

```text
GOFLAGS = -mod=readonly -tags=
```

overrides a persisted `GOFLAGS=-tags=ambient` setting and keeps an ambient-tagged file out of the candidate `go list` selection. That is useful design evidence only. The normalization is **not promoted into the scanner plan yet**, because the real govulncheck runtime is unavailable in the current validation environment and UPM has not reviewed the resulting scanner/`go/packages` behavior end to end.

Until that real-runtime check is completed, ambient/persisted `GOFLAGS` is an explicit remaining build-selection limitation and promotion blocker rather than hidden evidence.

## Test-enabled mode fails closed

Even when both planned command lines request tests, UPM currently returns:

```text
matches = false
difference = test-enabled selection equivalence is not established
```

This is deliberate. Govulncheck configures `go/packages` with test loading, while `go list -test` expands test/package variants through the Go command. UPM will not call those two representations equivalent until the optional real-scanner alignment path proves that the declaration/selection model is safe for this use.

## Interpretation

A successful default alignment means only:

```text
scope = planned-go-symbol-build-selection-alignment
patterns/tags/tests = planned consistently
ambient_GOFLAGS_equivalence = not-established
freshness = not-established
govulncheck_runtime_equivalence = not-established
```

It does **not** establish:

- identical `go/packages` runtime loading;
- identical selected syntax/type information;
- immunity from ambient or persisted `GOFLAGS` selection changes;
- unchanged source files;
- unchanged GOOS/GOARCH/CGO/toolchain state;
- identical call graphs;
- runtime/data-flow reachability;
- exploitability.

## Validation

Run from a normal private checkout:

```sh
sh ./scripts/test-go-symbol-build-selection.sh
sh ./scripts/test-go-symbol-prepublic-all.sh
```

Focused reconstructed validation in the constrained development environment passed **6/6** build-selection checks. The separate Go 1.23.2 `GOFLAGS` experiment described above is not counted as an additional passing build-selection regression because the scanner side has not run.
