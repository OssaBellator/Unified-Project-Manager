# Implementation status

This document records the current `feature/initial-control-plane` branch. It distinguishes public behavior from pre-public groundwork and deliberate gaps.

## Public surface

The public relationship-provider surface remains exactly eight families: Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM.

Public behavior includes mixed-project discovery/workspace control, preview-first mutations and receipts, health/policy/status, native graph/why/impact, fleet inventory/duplicates, CycloneDX 1.7/SPDX 2.3, preview-first OSV scanning with exact scanned-SBOM evidence, Go/Cargo physical cache provenance, and opt-in Go package-import advisory reachability.

No GitHub Actions workflows are used. Aggregate local validation:

```sh
sh ./scripts/check-all-local-latest.sh
```

## Public Go package-import reachability

`--go-import-reachability` remains report-only, component-scoped, `GOPROXY=off` + `GOWORK=off`, any-build-tag/test-import-aware, replacement-aware, and explicitly weaker than symbol/runtime/exploitability evidence. A real local Go 1.23.2 regression confirms `go mod why -m` leaves `go.mod`/`go.sum` unchanged.

## Pre-public Go symbol/call-graph stack

Vulnerable-symbol reachability is still **not public**, but lower-level groundwork now includes:

1. strict govulncheck v1 source/symbol/local-DB parser/planner;
2. strict correlation to existing UPM Go advisory impacts by exact component + GO-ID/alias + effective module + exact version;
3. read-only preflight requiring exact project/DB/executables and telemetry already `off`;
4. fail-closed executor gated by the exact ready preflight;
5. shared project/fleet reporting over already-built execution/correlation results;
6. deterministic synthetic vulnerability-DB + local versioned module-proxy/runtime fixtures;
7. an optional real govulncheck end-to-end regression gated by already-satisfied tool/telemetry prerequisites;
8. a public-boundary regression keeping govulncheck out of the eight-provider registry.

### Self-contained offline fixture

The repo can now generate its own local Go vulnerability DB v1 fixture and versioned dependency source. The DB uses only the published filesystem endpoints (`index/db.json`, `index/modules.json`, `index/vulns.json`, `ID/<GO-ID>.json`). The runtime fixture exposes `example.com/dep@v1.2.3` through a generated `file://` Go module proxy and uses isolated `GOMODCACHE`/`GOCACHE` directories.

Fixture setup runs `go mod download` only against that local file proxy with checksum-DB access disabled. The actual analysis environment then switches to `GOPROXY=off`. A real installed Go 1.23.2 check confirms the cached dependency resolves offline after that transition.

Manual fixture helper:

```sh
sh ./scripts/prepare-go-symbol-validation-fixture.sh /tmp/upm-go-symbol-fixture
```

This removes downloaded public DB and network dependency source as prerequisites for future real govulncheck validation.

### Executor/reporting

The executor uses the preflight-resolved executable directly with no shell and the offline environment:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

Govulncheck JSON mode exit 0 means “command completed”; findings come from validated JSON. Nonzero is execution failure. Malformed JSON, reported-DB mismatch, or preflight/plan mismatch fail closed.

A successful execution can produce strict matched/unmatched symbol correlation. Failed/blocked/invalid execution leaves `correlation=null`; fleet reporting keeps execution failure, raw findings, correlated matches, and unmatched findings separate.

Everything remains:

```text
public = false
persisted = false
runtime_reachability = not-evaluated
exploitability = not-established
```

### Optional real-runtime test

`tests/test_go_symbol_real_runtime.py` is committed and included in the local symbol driver. It skips unless `go` and `govulncheck` already exist and `GOTELEMETRY` is already `off`. It never installs a tool or changes telemetry.

When runnable, it creates only local fixtures, pre-populates the isolated versioned module cache, snapshots the project, executes UPM preflight/executor/correlation/reporting, requires the synthetic symbol result, and requires the entire project snapshot to remain unchanged.

The deterministic DB/source fixtures are therefore no longer live blockers. In this environment the remaining prerequisites are:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
```

No install or telemetry mutation was performed.

### Persistence/freshness still deferred

UPM has not invented a persisted symbol-evidence fingerprint. A correct freshness model must conservatively represent the actual source/build configuration govulncheck analyzed. It should not reuse only `go.mod`/`go.sum` or the scanned SBOM as a call-graph freshness proxy.

See `GO_SYMBOL_REACHABILITY.md`.

## Cache/storage boundary

Public Go/Cargo provenance remains observation-only; no unattributed→unused or reclaim inference. Opaque npm/pnpm/uv physical cache internals remain unsupported rather than heuristically reverse-engineered.

## Focused validation state

The full private branch cannot be materialized end-to-end here. Focused reconstructed/local results include:

- Poetry/PDM reachability: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- cache physical mapping: **5/5** plus precision checks;
- cache report semantics: **7/7** plus identity checks;
- Go package-import reachability: **7/7**;
- Go relationship environment isolation: **3/3**;
- real local Go import-query immutability: **1/1**;
- govulncheck parser/planner: **8/8**;
- strict symbol correlation: **9/9**;
- govulncheck preflight: **6/6**;
- fail-closed govulncheck executor: **9/9**;
- shared project/fleet symbol reporting: **6/6**;
- deterministic Go vulnerability-DB fixture: **7/7**;
- fully local versioned runtime fixture: **5/5**, including real Go local-proxy → offline-cache resolution;
- optional real govulncheck end-to-end regression: committed but skipped here because prerequisites are not met.

## Important remaining gaps

1. run the optional real govulncheck regression when the binary already exists and telemetry is already `off`, then characterize actual non-project cache/tool side effects;
2. prove strict correlation against that real govulncheck stream;
3. define a conservative source/build-state fingerprint plus separate symbol persistence/freshness semantics before public routing;
4. add runtime/data-flow or exploitability evidence only where ecosystem-native evidence supports it;
5. deepen physical cache provenance only where manager-native identity supports it;
6. run the full large branch from one materialized private checkout when available;
7. eventually implement SPDX 3.x as a dedicated model.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
