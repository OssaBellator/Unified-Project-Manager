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

## Effective `GOFLAGS` fails closed for real-runtime alignment

The command-line comparator is deliberately only an **argv plan** comparison. `GOFLAGS` can supply default Go command flags, including build tags, from either the process environment or values saved by `go env -w`.

An empty operating-system `GOFLAGS` variable is not by itself a sufficient normalization strategy because the Go command may then use a persisted value. UPM therefore does not treat argv-level `tags = []` as proof that no ambient build tags affected a real scanner run.

The candidate observation already retains the effective `GOFLAGS` value reported by its preceding `go env -json`. `go_symbol_effective_goflags_blocker(...)` now requires that retained value to be present and exactly empty before the optional real govulncheck alignment may continue.

The promotion paths behave conservatively:

```text
GOFLAGS missing   -> real alignment blocked
GOFLAGS non-empty -> real alignment blocked
GOFLAGS empty     -> argv pattern/tag/test comparison may continue
```

`tests/test_go_symbol_real_alignment.py` skips rather than launches govulncheck when this effective-environment gate is not satisfied. The characterization command returns exit `2`, `status = blocked`, and phase `effective-goflags`; it records the source-observation side effects but does not launch govulncheck. Blocked is not a pass.

UPM does **not** change or clear the user's `GOFLAGS` setting.

A local Go 1.23.2 experiment separately showed that a non-empty process value such as:

```text
GOFLAGS = -mod=readonly -tags=
```

overrides a persisted `GOFLAGS=-tags=ambient` setting and keeps an ambient-tagged file out of candidate `go list` selection. That remains design evidence only. UPM has not promoted this normalization into the scanner environment because real govulncheck/`go/packages` behavior with that override still needs end-to-end validation.

Thus the current safe promotion candidate is narrower: real-runtime validation is attempted only where effective `GOFLAGS` is already exactly empty.

## Test-enabled mode fails closed

Even when both planned command lines request tests, UPM currently returns:

```text
matches = false
difference = test-enabled selection equivalence is not established
```

This is deliberate. Govulncheck configures `go/packages` with test loading, while `go list -test` expands test/package variants through the Go command. UPM will not call those two representations equivalent until the optional real-scanner alignment path proves that the declaration/selection model is safe for this use.

## Interpretation

A successful argv-level default alignment means only:

```text
scope = planned-go-symbol-build-selection-alignment
patterns/tags/tests = planned consistently
freshness = not-established
govulncheck_runtime_equivalence = not-established
```

The optional real-runtime gate additionally requires:

```text
effective_GOFLAGS = ""
```

Neither condition establishes:

- identical `go/packages` runtime loading;
- identical selected syntax/type information;
- equivalence for non-empty ambient/persisted `GOFLAGS`;
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

Focused reconstructed validation in the constrained development environment passed **6/6** argv build-selection checks. The new effective-environment helper passed **3/3** focused cases (empty, non-empty, and missing `GOFLAGS`) and **14/14** when run together with the published source-observation hardening regressions.

The separate Go 1.23.2 persisted-`GOFLAGS` experiment is not counted as scanner equivalence because govulncheck is unavailable in the current environment.
