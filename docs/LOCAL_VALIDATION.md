# Local-only validation

Unified Project Manager deliberately does not use GitHub Actions in this repository. Validation is intended to run from a local checkout with Python 3.11+ and ecosystem-native tools already available where a test requires them.

## Main entrypoints

Unix-like hosts:

```sh
sh ./scripts/check.sh
sh ./scripts/test-integration.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
sh ./scripts/test-sbom-project-components.sh
sh ./scripts/test-cache-provenance.sh
sh ./scripts/test-go-import-reachability.sh
sh ./scripts/test-go-symbol-prepublic-all.sh
sh ./scripts/check-all-local-latest.sh
```

Windows PowerShell:

```powershell
./scripts/build.ps1
./scripts/test.ps1
./scripts/check-all-local-latest.ps1
```

`test.ps1` accepts optional test file names or paths, so focused regressions can run without a hosted CI service. `check-all-local-latest.sh` includes the complete pre-public Go symbol stack; the PowerShell aggregate compiles `src`/`tests` and runs the full standard-library unittest discovery suite. No command above invokes GitHub Actions.

## Public Go package-import reachability

The dedicated driver covers `GOPROXY=off` + `GOWORK=off`, any-build-tag/test-import semantics, replacements, positive/negative/query-failed states, project/fleet routing, report-only semantics, and a real local Go check proving `go mod why -m` leaves `go.mod`/`go.sum` unchanged.

## Pre-public Go vulnerable-symbol stack

The complete local stack covers:

- strict govulncheck parser/planner and mandatory scanner SBOM;
- strict scanner-build-list/advisory/module/version correlation;
- public-boundary regression;
- read-only preflight;
- fail-closed executor;
- shared project/fleet reporting;
- deterministic local vulnerability DB and versioned module-proxy fixtures;
- scan-declaration provenance identity;
- planned package-pattern/tag/test alignment;
- candidate Go-native source/build observation;
- Go-native vs scanner-SBOM declaration alignment;
- optional real govulncheck execution and alignment.

### Deterministic runtime fixture

The repo writes its own Go vulnerability DB v1, `example.com/dep@v1.2.3` module proxy, tiny app, and isolated `GOMODCACHE`/`GOCACHE`. Setup uses only the generated `file://` proxy; actual analysis runs with `GOPROXY=off`.

A real Go 1.23.2 check confirms the versioned dependency remains resolvable after the proxy-to-offline transition.

### Planned build-selection guard

The scanner and candidate-observation plans are compared before optional real scanner execution. Current accepted selection:

```text
patterns = ["./..."]
tags = []
tests = false
```

Test-enabled selection remains deliberately unproven even when both plans request it.

Focused reconstructed result: **6/6**.

### Candidate source/build observation

The candidate now requires Go 1.21+ and runs the normalized loader command:

```text
go env -json
go list -e -mod=readonly -deps=true -compiled=true -test=false \
  -export=false -find=false -buildvcs=false -pgo=off -json -- ./...
```

It retains broad selected build inputs and `CompiledGoFiles` separately as syntax/type-check inputs. It never labels them freshness evidence.

The exact command was run with installed Go 1.23.2 in a temporary module:

```text
env exit          = 0
list exit         = 0
GoFiles           = [main.go]
CompiledGoFiles   = [main.go]
IgnoredGoFiles    = [windows_only.go]
project snapshot  = unchanged
```

Go versions below 1.21 are refused for this candidate before package loading rather than silently using a different loader profile.

### Optional real govulncheck tests

Real scanner tests skip unless:

- `go` already exists;
- `govulncheck` already exists;
- `go env GOTELEMETRY` is already exactly `off`.

They never install govulncheck or change telemetry. Before launching the scanner they also require planned package-pattern/tag/test alignment.

The Go-native fixture evidence above was produced in an environment with:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
Go version = 1.23.2
GOTELEMETRY = local
```

The Windows PowerShell aggregate is intentionally tool-tolerant: real-Go and real-govulncheck regressions skip when their prerequisites are absent rather than installing tools or changing telemetry.

Govulncheck v1.6.0 itself declares Go 1.25.0 and x/tools v0.48.0, so real scanner alignment is still necessary; local Go 1.23.2 observation is not treated as scanner-runtime proof.

## Focused reconstructed/local results

- Poetry/PDM reachability: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- cache physical mapping: **5/5** plus precision checks;
- cache report semantics: **7/7** plus identity checks;
- Go package-import reachability: **7/7**;
- Go relationship environment isolation: **3/3**;
- real local Go import-query immutability: **1/1**;
- govulncheck parser/planner baseline: **8/8**;
- strict symbol correlation baseline: **9/9**;
- govulncheck preflight: **6/6**;
- fail-closed govulncheck executor baseline: **9/9**;
- shared project/fleet symbol reporting: **6/6**;
- deterministic vulnerability-DB fixture: **7/7**;
- fully local versioned runtime fixture: **5/5**;
- scan-SBOM focused invariants: **12/12**;
- scan-declaration identity: **5/5**;
- planned build-selection alignment: **6/6**;
- normalized Go source-observation command: real Go 1.23.2 success with unchanged project snapshot;
- optional real govulncheck execution/alignment: **committed but prerequisite-gated**.

Current Windows checkout validation: **745 tests run, 0 failures, 7 skips**. The skips are limited to unavailable Go/govulncheck prerequisites and Windows symlink-creation privilege, so they remain explicit environment gaps rather than hidden passes. The Linux sandbox available here lacks `python3`, so the Unix aggregate could only be checked through shell startup/line-ending handling, not executed end-to-end in that container.
