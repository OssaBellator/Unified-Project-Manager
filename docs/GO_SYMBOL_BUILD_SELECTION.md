# Go symbol build-selection guard

This document describes another **pre-public** trust boundary for Go vulnerable-symbol analysis. It does not create a public provider, CLI flag, persisted freshness record, or execution path.

## Why this exists

Govulncheck source mode loads the user-supplied package patterns through `golang.org/x/tools/go/packages`. Its source loader can vary package selection using:

- package patterns;
- build tags;
- test inclusion.

UPM's candidate source/build observation uses `go list` to observe Go-selected package/source inputs. If those package-selection knobs drift between the govulncheck plan and the observation plan, any later comparison is meaningless even before source-file freshness is considered.

## Current supported candidate

The current UPM pre-public plans both select:

```text
patterns = ["./..."]
tags = []
tests = false
```

`compare_go_symbol_build_selection(...)` parses both planned command lines and requires package patterns and build tags to agree.

Build-tag ordering is normalized because the tag set, not comma-list ordering, controls selection.

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
freshness = not-established
govulncheck_runtime_equivalence = not-established
```

It does **not** establish:

- identical `go/packages` runtime loading;
- identical selected syntax/type information;
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

Focused reconstructed validation in the constrained development environment passed **6/6** build-selection checks.
