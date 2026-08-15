# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Anything described as follow-up should not be inferred as implemented public capability.

## Public native providers

The public native-provider surface remains exactly Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Govulncheck is **not** a public provider and has no public CLI route.

## Public evidence boundaries

Poetry/PDM remain public certainty-aware structured-lock providers. Mixed-project SBOM topology remains deterministic and topology-only. Go/Cargo physical cache provenance remains observation-only with no reclaim inference.

Go component-scoped relationship execution remains isolated with:

```text
GOPROXY = off
GOWORK = off
```

A real local Go 1.23.2 regression confirms `go mod why -m` leaves `go.mod` and `go.sum` byte-for-byte unchanged.

## Public Go package-import reachability

The first public stronger-than-dependency layer remains the explicit Go-only audit enrichment:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

It is report-only, requires full native scan inventory, uses component-scoped offline `go mod why -m`, and never upgrades package-import evidence into current-build, API/symbol, runtime, or exploitability claims.

Each row preserves the any-build-tag/test-import caveat and Go replacement distinction between logical query module and effective replacement advisory identity. It is not written into persisted OSV evidence.

See `REACHABILITY_EVIDENCE.md`.

## Pre-public Go vulnerable-symbol groundwork

The branch now contains four lower-level govulncheck layers, all still **pre-public**:

1. **Parser/planner** — exact govulncheck protocol `v1.0.0`, explicit source/symbol mode, local `file://` DB, module/package/symbol finding separation, offline execution guards.
2. **Strict correlation** — symbol findings attach only to existing `go-modules` advisory impacts for the same component when govulncheck OSV/alias identity, effective module, and exact version all agree.
3. **Read-only preflight** — revalidates project, local DB, Go/govulncheck executables, and `go env GOTELEMETRY`; does not launch govulncheck or change telemetry settings.
4. **Public-boundary regression** — the provider registry remains the same eight public relationship providers and the public Go provider metadata explicitly retains both `GOPROXY=off` and `GOWORK=off`.

### Correlation refusal rules

Alias overlap alone never creates a match. The correlator refuses:

- wrong component/provider;
- effective-module mismatch;
- missing govulncheck module version;
- exact-version mismatch;
- multiple UPM advisory aliases competing for one govulncheck finding.

Duplicate exact UPM impacts consolidate dependency paths rather than multiplying the symbol claim.

For Go replacements, govulncheck correlation uses the effective replacement module identity, while `go mod why -m` import reachability continues to query the logical/original module namespace. Those are deliberately separate semantics.

### Offline/preflight boundary

The planned future govulncheck command uses a caller-supplied local vulnerability DB and environment guards:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
telemetry mode required = off
```

Preflight is inspection-only and reports `executes_govulncheck=false`, `mutates_telemetry_configuration=false`, and `project_mutation=none` for the preflight itself.

The live environment remains not ready: Go is installed, telemetry is `local`, govulncheck is absent, and no candidate local vulnerability DB was found. UPM did not install a tool, download a DB, or alter telemetry to bypass those blockers.

### Still not implemented/public

There is still no govulncheck subprocess executor or `--go-symbol-reachability` public flag. No real symbol scan is claimed.

Public promotion remains blocked on:

- fail-closed executor implementation and real local-DB runtime validation;
- project-state and non-project cache/tool side-effect characterization;
- binding strict correlation to real output;
- shared project/fleet presentation;
- separate symbol-evidence persistence/freshness semantics;
- ordinary status remaining free of hidden symbol analysis.

Because the no-network plan sets `GOSUMDB=off`, future symbol evidence must not be described as fresh dependency-integrity verification.

See `GO_SYMBOL_REACHABILITY.md`.

## Stronger reachability not claimed

UPM still has no public vulnerable-symbol provider, runtime/data-flow provider, or exploitability determination. Dependency paths, Go package-import paths, and pre-public parser/correlation data must not be promoted into those claims.

## Exact advisory evidence contract

Project and fleet advisory flows retain and fingerprint the exact CycloneDX document scanned by OSV-Scanner. Native inventory is not rebuilt after scanning, successful scanner output without the exact scanned BOM is an evidence failure, and ordinary status never reruns scanner/providers merely to manufacture freshness.

## Local validation boundary

No GitHub Actions workflow is part of this project.

Aggregate local driver:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused reconstructed/local validation in this execution environment includes:

- Poetry/PDM reachability hardening: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5** plus additional Cargo precision checks;
- cache provenance report semantics: **7/7** plus separate identity-precision checks;
- Go package-import reachability core: **7/7**;
- Go relationship execution environment: **3/3**;
- real local Go 1.23.2 source-query immutability: **1/1**;
- pre-public govulncheck parser/planner: **8/8**;
- strict govulncheck-to-UPM symbol correlation: **9/9**;
- govulncheck preflight: **6/6**.

The full private branch still cannot be materialized and run end-to-end here. The committed local drivers are intended for a normal private checkout and are not represented as fully executed in this constrained runtime.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
