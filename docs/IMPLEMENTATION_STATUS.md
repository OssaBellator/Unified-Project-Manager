# Implementation status

This document records the current `feature/initial-control-plane` branch and separates public behavior from pre-public groundwork and deliberate gaps.

## Public surface

The public relationship-provider surface remains exactly eight families: Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM.

Public behavior includes mixed-project discovery/workspace control, preview-first mutations and receipts, native graph/why/impact, all-provider fleet inventory/duplicates, CycloneDX 1.7/SPDX 2.3, preview-first OSV scanning with exact scanned-SBOM evidence, Go/Cargo physical cache provenance, and opt-in Go package-import advisory reachability.

No GitHub Actions workflows are used. Aggregate validation remains local:

```sh
sh ./scripts/check-all-local-latest.sh
```

On Windows PowerShell the full compile/unittest aggregate is available as:

```powershell
./scripts/check-all-local-latest.ps1
```

The Unix aggregate includes the complete pre-public Go symbol validation stack; optional real-govulncheck checks skip unless their prerequisites already exist. The PowerShell aggregate provides a GitHub-Actions-free full Python regression path for Windows checkouts.

## Public Go package-import reachability

`--go-import-reachability` remains report-only, component-scoped, `GOPROXY=off` + `GOWORK=off`, any-build-tag/test-import-aware, replacement-aware, and explicitly weaker than symbol/runtime/exploitability evidence. A real local Go 1.23.2 regression confirms `go mod why -m` leaves `go.mod`/`go.sum` unchanged.

## Pre-public Go symbol/call-graph stack

Vulnerable-symbol reachability is still **not public**. Current groundwork includes:

1. strict govulncheck v1 source/symbol/local-file-DB parser/planner;
2. mandatory native govulncheck scan-SBOM retention;
3. strict correlation requiring scanner build-list + component + GO-ID/alias + effective module + exact version agreement;
4. read-only project/DB/executable/telemetry preflight;
5. fail-closed subprocess executor;
6. shared project/fleet reporting;
7. deterministic local vulnerability-DB and versioned dependency/module-proxy fixtures;
8. optional real scanner execution/alignment regressions;
9. scanner-declaration identity for provenance only;
10. Go-native candidate source/build observation;
11. planned package-pattern/tag/test alignment guard;
12. public-boundary regression keeping govulncheck out of the eight-provider registry.

Everything remains:

```text
public = false
persisted = false
runtime_reachability = not-evaluated
exploitability = not-established
```

### Native scan-SBOM trust chain

Accepted source-symbol JSON requires exactly one native govulncheck `SBOM` message. Missing, duplicate, malformed, or rootless scan-SBOM evidence is invalid even after exit 0.

Before a symbol finding attaches to an existing UPM advisory impact, its vulnerable module/version must also exist in the scanner-declared build list.

### Scan declaration identity

`govulncheck_scan_declaration_identity(...)` hashes scanner-declared protocol/scanner identity, `scan_mode`, `scan_level`, local DB declaration/modification time, config/SBOM Go versions, normalized module build list, and roots.

It explicitly remains:

```text
scope = govulncheck-scan-declaration
freshness = not-established
source_state_fingerprint = false
build_configuration_fingerprint = false
```

### Planned build-selection guard

UPM parses the scanner and candidate-observation command plans and compares package patterns, build tags, and test inclusion.

The current accepted candidate is:

```text
patterns = ["./..."]
tags = []
tests = false
```

Pattern/tag/test drift is explicit. Test-enabled mode stays fail-closed even when both plans request tests because runtime equivalence between govulncheck's `go/packages` test loading and `go list -test` variants has not been proven.

Focused reconstructed validation: **6/6**.

### Candidate source/build observation

The candidate freshness input now requires **Go 1.21+** and uses a normalized Go-list profile:

```text
go env -json
go list -e -mod=readonly -deps=true -compiled=true -test=false \
  -export=false -find=false -buildvcs=false -pgo=off -json -- ./...
```

with `GOPROXY=off`, `GOWORK=off`, `GOSUMDB=off`, and `GOTOOLCHAIN=local`.

The observation retains resolved build environment, original/effective module identities, broader selected build inputs, ignored files, imports, and `CompiledGoFiles` separately as `syntax_go_files` because current `go/packages` syntax/type loading is based on compiled Go files.

This is still candidate evidence:

```text
scope = candidate-govulncheck-source-build-inputs
freshness = not-established
govulncheck_equivalence = not-established
source_state_fingerprint = false
```

A real local Go 1.23.2 check confirms the normalized loader command succeeds, honors build-tag exclusion, and leaves the project snapshot unchanged.

Current govulncheck v1.6.0 itself declares Go 1.25.0 and x/tools v0.48.0. That makes the optional real scanner alignment especially important; successful local Go 1.23.2 observation does not imply scanner-runtime equivalence.

### Self-contained real-runtime fixture

The repo generates a synthetic Go vulnerability DB v1, versioned `example.com/dep@v1.2.3` file module proxy, app calling the synthetic vulnerable `Danger` symbol, and isolated Go caches. Fixture setup contacts only the generated `file://` proxy; analysis switches to `GOPROXY=off`.

Real Go validation already confirms local-proxy -> offline-cache resolution.

Optional real scanner tests additionally require:

```text
govulncheck executable = present
GOTELEMETRY = off
```

They never install govulncheck or mutate telemetry. Before scanner launch they now also require planned build-selection alignment.

The Go-native fixture evidence above was produced with these remaining scanner prerequisites unmet:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
```

The Windows full-suite runner does not install missing tools or change telemetry; real-Go/govulncheck regressions skip when those prerequisites are unavailable.

### Persistence/freshness still deferred

UPM has **not** created a persisted symbol freshness fingerprint. Neither `go.mod`/`go.sum`, the scanner SBOM, the scan-declaration SHA, nor the Go-native observation alone is accepted as freshness proof.

A public/persisted symbol route remains blocked until real govulncheck execution proves scanner/observation alignment and actual project/non-project side effects are characterized.

## Cache/storage boundary

Public Go/Cargo provenance remains observation-only. Unattributed bytes do not imply unused bytes or reclaim permission. Opaque npm/pnpm/uv physical cache internals remain unsupported rather than heuristically reverse-engineered.

## Focused validation state

The private branch is materialized locally and its full Python regression suite runs through the PowerShell aggregate. Ecosystem-native checks still remain prerequisite-gated. Focused evidence includes:

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
- scan-SBOM trust-chain focused invariants: **12/12**;
- scan-declaration identity: **5/5**;
- planned build-selection alignment: **6/6**;
- real Go normalized source-observation command: successful on Go 1.23.2 with project snapshot unchanged;
- Windows PowerShell aggregate: **745 tests, 0 failures, 7 environment-dependent skips**;
- optional real govulncheck execution/alignment: committed and prerequisite-gated.

## Important remaining gaps

1. run real govulncheck against the generated local fixture when the executable exists and telemetry is already `off`;
2. validate declaration/source-selection alignment and strict correlation against that real stream;
3. characterize project and non-project cache/tool side effects from the real scanner;
4. only then define conservative persisted symbol freshness semantics;
5. add runtime/data-flow or exploitability evidence only where ecosystem-native evidence supports it;
6. deepen physical cache provenance only where manager-native identity supports it;
7. run the Unix aggregate in a local environment that has Python 3.11+ plus the relevant ecosystem-native tools;
8. eventually implement SPDX 3.x as a dedicated model.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM should fail closed on ambiguity rather than substitute a universal guess for ecosystem-specific truth.
