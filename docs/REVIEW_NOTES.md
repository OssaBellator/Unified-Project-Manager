# Current review notes

These notes capture the review boundary for `feature/initial-control-plane`. Pre-public work must not be inferred as public capability.

## Public boundary

The public relationship-provider surface remains exactly Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Govulncheck is **not** public and has no CLI/provider route.

Public Go package-import reachability remains report-only, `GOPROXY=off` + `GOWORK=off`, replacement-aware, and weaker than symbol/runtime/exploitability evidence.

A regression locks the provider registry at exactly eight entries and explicitly rejects govulncheck/go-symbol provider names.

## Pre-public Go symbol trust chain

The branch now contains:

1. strict source/symbol/local-file-DB parser/planner;
2. mandatory scanner-native SBOM retention;
3. scanner-build-list + advisory/module/version strict correlation;
4. read-only preflight;
5. fail-closed executor;
6. shared project/fleet reporting;
7. deterministic local DB and versioned dependency fixtures;
8. scanner-declaration provenance identity;
9. planned scanner/observation build-selection alignment;
10. candidate Go-native source/build observation;
11. optional real scanner execution/alignment tests;
12. public-boundary regression.

### Scanner-SBOM and correlation boundary

Accepted symbol evidence requires one valid govulncheck scan SBOM. The vulnerable frame's module/version must exist in that scanner-declared build list before UPM considers advisory correlation.

Correlation then additionally requires exact component/provider, GO OSV ID or alias from the exact OSV record, effective module, and exact non-missing version. Replacement correlation uses effective module identity.

### Executor boundary

The executor launches only after a ready preflight for the exact project/DB, invokes the resolved executable directly, preserves offline guards, never retries online, and never mutates telemetry settings.

JSON exit 0 means command completion even when vulnerabilities exist. Nonzero exit is execution failure; stdout from a failed process is not accepted as symbol evidence.

### Scanner-declaration identity boundary

The deterministic scanner-declaration SHA includes protocol/scanner identity, `scan_mode`, `scan_level`, local DB declaration/modification time, config/SBOM Go versions, module build list, and roots.

It remains provenance only:

```text
freshness = not-established
source_state_fingerprint = false
build_configuration_fingerprint = false
```

### Planned build-selection boundary

Scanner and candidate-observation plans must agree on package patterns, build tags, and test inclusion before optional real scanner tests launch.

Current accepted candidate:

```text
patterns = ["./..."]
tags = []
tests = false
```

Test-enabled selection fails closed even when both plans request tests because runtime equivalence between govulncheck `go/packages` test loading and `go list -test` variants is not proven.

### Candidate source/build observation boundary

The candidate observation requires Go 1.21+ and runs a normalized Go-list profile with compiled/dependency loading, tests/export/find disabled, VCS stamping disabled, and PGO disabled:

```text
go list -e -mod=readonly -deps=true -compiled=true -test=false \
  -export=false -find=false -buildvcs=false -pgo=off -json -- ./...
```

It records resolved build environment, broader selected build inputs, ignored files, module/replacement identity, imports, and `CompiledGoFiles` separately as syntax/type-check inputs.

A real local Go 1.23.2 check confirms this exact command succeeds, respects a build-tagged-out Windows file, and leaves the project snapshot unchanged.

This is still explicitly:

```text
freshness = not-established
govulncheck_equivalence = not-established
source_state_fingerprint = false
```

Current govulncheck v1.6.0 declares Go 1.25.0 and x/tools v0.48.0. Local Go 1.23.2 observation therefore cannot substitute for real scanner alignment.

### Shared reporting boundary

Failed/blocked/invalid execution leaves `correlation=null`; UPM never turns provider failure into a negative reachability result. Fleet aggregation never reruns analysis and keeps execution failures, raw symbols, correlated matches, and unmatched findings separate.

### Persistence/side-effect boundary

Symbol evidence remains `persisted=false`. No source/build freshness fingerprint exists.

Do not reuse `go.mod`/`go.sum`, dependency graph, scanned SBOM, scanner-declaration SHA, or candidate source observation alone as call-graph freshness proof.

```text
project mutation = none planned; real scanner verification still required
non-project cache/tool mutation = possible
runtime reachability = not evaluated
exploitability = not established
```

The deterministic DB and versioned dependency source are no longer blockers. In this environment real scanner execution remains blocked because govulncheck is absent and `GOTELEMETRY=local`; neither condition was changed automatically.

## Remaining promotion gate

Do not add public symbol routing until:

- real local-fixture govulncheck execution passes preflight;
- real scanner declaration/source-selection alignment is characterized;
- project and non-project cache/tool side effects are characterized;
- strict correlation is proven against real output;
- a conservative source/build freshness and persistence model exists;
- ordinary status remains free of hidden symbol execution.

## Validation boundary

No GitHub Actions workflow is used. Current focused evidence includes the earlier public-provider/cache/SBOM slices plus:

- Go import reachability: **7/7**;
- real Go import-query immutability: **1/1**;
- govulncheck parser/planner baseline: **8/8**;
- strict correlation baseline: **9/9**;
- preflight: **6/6**;
- executor baseline: **9/9**;
- shared symbol reporting: **6/6**;
- deterministic vulnerability DB: **7/7**;
- fully local runtime fixture: **5/5**;
- scanner-SBOM focused invariants: **12/12**;
- scan declaration identity: **5/5**;
- planned build-selection alignment: **6/6**;
- normalized Go source-observation command: real Go 1.23.2 success, project snapshot unchanged.

The full private branch still cannot be materialized/run end-to-end here.

## Merge hygiene

The branch contains many small contents-API commits. If/when merge is explicitly authorized, squash merge remains the appropriate default.

Do not merge this PR without explicit user authorization.
