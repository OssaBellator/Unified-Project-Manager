# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Anything described as follow-up should not be inferred as implemented public capability.

## Public native providers

The public native-provider surface consists of Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Public graph/why/impact/fleet/SBOM/advisory behavior is documented in `NATIVE_PROVIDERS.md`; Poetry/PDM's conservative structured-lock contract is detailed in `PYTHON_LOCK_PROVIDERS.md`. Yarn Classic remains outside the Berry provider.

## Yarn Berry boundary

The Berry provider preserves exact descriptor/locator and workspace/virtual identity. Network access is disabled inside Berry, install state is redirected outside the project, telemetry is suppressed, and supported cache mutation is blocked. Hardened mode is left unchanged. SBOM/advisory/fleet inventory includes only locators reachable from active project/workspace roots.

## Poetry/PDM public uncertainty model

Poetry/PDM are public as `poetry-lock` and `pdm-lock`, sharing `structured-lock-dependency-graph` scope. Public routing includes graph, why, project/fleet impact, CycloneDX/SPDX, project/fleet advisory, provider status, and fleet native inventory/duplicate correlation.

The shared reachability model distinguishes resolved `packages` from ambiguity-derived `possible_packages`, renders unresolved hops as `?dependency`, propagates possible state through candidate descendants, preserves marker/optional conditions and distinct paths, uses explicit path/search budgets, and surfaces truncation rather than hiding incomplete explanations. Advisory correlation reuses the exact validated structured-lock result that produced the scanned BOM.

## All-provider fleet inventory

`projects inventory --native` and `projects duplicates --native` cover all eight public provider families while preserving provider-specific occurrence evidence. Cross-project duplicate groups remain observation-only with `reclaimable=false`.

## Mixed-project SBOM topology

Aggregate SBOMs include a deterministic project topology layer; see `SBOM_PROJECT_COMPONENTS.md`. CycloneDX uses one aggregate application root plus one application anchor per discovered component. SPDX mirrors that model with aggregate/component `APPLICATION` packages and aggregate `CONTAINS` relationships. Anchor identity is clone-location-independent and the topology layer does not manufacture component→package edges from generic normalized inventory.

## Public cache provenance boundary

`upm cache provenance` is public for Go and Cargo physical attribution over explicitly registered projects. It is an observation command, not a cleanup planner.

Go physical identity starts from selected module directories returned by the offline native graph and may attribute selected-version `.info`, `.mod`, `.zip`, and `.ziphash` files only by reusing the already-escaped native physical path. Noncanonical paths are not guessed; `GOCACHE` remains outside selected-module attribution.

Cargo physical identity starts from native `manifest_path` and is normalized to canonical registry or git source objects:

```text
CARGO_HOME/registry/src/<index>/<crate-version>
CARGO_HOME/git/checkouts/<repo>/<revision>
```

One multi-crate git checkout is a legitimate multi-package physical container and is measured once. One registry source object is expected to identify one package; multiple identities are an explicit conflict. Index/cache/db/shallow/noncanonical/path locations remain outside source-object attribution.

`--closed-universe` is an explicit registry assertion and is separate from `observation_complete`. Missing projects, provider/storage failures, applicable provider gaps, contradictory physical identities, or byte inconsistencies make the observation incomplete.

Safety fields remain unconditional:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv physical package-cache provenance remains deliberately unsupported instead of heuristically reverse-engineering opaque cache/store layouts merely to claim coverage.

## Go relationship execution boundary

Component-scoped Go relationship execution is intentionally isolated from both network fallback and ambient workspace context:

```text
GOPROXY = off
GOWORK = off
```

This applies to the native selected-module/requirement graph and `go mod why -m` path queries. Explicit Go workspace commands remain on their separate workspace-owned path.

The Go `why` implementation also sets the module loader's explicit-write guard. Go documents that this prevents package/module loading from updating `go.mod` and `go.sum` unless the command later explicitly writes them; `go mod why` does not. A real local Go 1.23.2 regression additionally confirms byte-for-byte `go.mod` / `go.sum` immutability for the isolated query.

Reviewers should therefore treat this relationship/source-query boundary as project-state read-only, offline, and single-module scoped. Missing local module/package data is an explicit query/provider failure rather than a reason to contact a proxy or inherit an ambient `go.work`.

## Go package-import advisory reachability

The first public stronger-than-dependency reachability layer is Go-only and explicit:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

The flag requires full `--native` inventory. It is not accepted with compatibility-only `--native-go`, because source evidence must be tied to vulnerable Go module impacts already correlated to the retained native scan inventory.

After an applied scan, UPM uses component-scoped `go mod why -m`. Source-query states are explicit:

- `package-import-reachable`;
- `not-package-import-reachable`;
- `query-failed`.

Query failure is never converted to a successful negative. Multiple advisories for the same component/logical-module pair share one source query.

### Build-constraint boundary

The current Go command implementation loads `why` with an any-build-tag package graph. Tests may also contribute imports. Every source row therefore records:

```text
build_constraints = any-tags
current_build_configuration_reachability = not-evaluated
test_imports_may_contribute = true
api_reachability = not-evaluated
runtime_reachability = not-evaluated
exploitability = not-established
persisted = false
```

A positive result is not relabeled as reachability in the current production build. A negative result is likewise only a negative in Go's queried any-build-tag package graph; it is not an exploitability verdict.

### Replacement boundary

For versioned Go replacements, UPM retains both identities. `go mod why -m` queries the logical required/original module path used by imports, while advisory/package correlation can retain the effective replacement module identity separately:

```text
queried_module = <logical required module>
effective_module = <replacement identity>
replacement_active = true
```

The replacement-aware reachability regression prevents future code from silently querying the replacement module path as if it were the import-path namespace.

### Execution/persistence boundary

Preview remains non-executing. Source queries run only after an applied native scan and only for vulnerable Go impacts.

The exact OSV-scanned CycloneDX document and scanner result keep their existing persisted evidence contract. Go package-import evidence is **report-only** and is not written into `.upm/audits/osv.json`; ordinary status does not replay it as durable evidence.

Source-query failure does not invalidate an otherwise valid OSV scan/evidence record because advisory scan validity and source/import enrichment are separate evidence layers.

See `REACHABILITY_EVIDENCE.md`.

## Pre-public Go vulnerable-symbol groundwork

UPM still has **no public symbol-reachability command or provider route**. However, the branch now contains lower-level groundwork in `go_symbol_reachability.py` and `GO_SYMBOL_REACHABILITY.md`.

That groundwork models the official govulncheck streaming JSON protocol without flattening evidence classes:

- protocol must be exactly `v1.0.0`;
- scan mode must be explicitly `source`;
- scan level must be explicitly `symbol`;
- vulnerability database must be explicitly local (`file://...`);
- module-, package-, and symbol-level findings remain distinct;
- only a finding whose first trace frame names a function/method is treated as called-symbol evidence;
- Go OSV aliases are retained for future correlation, but alias overlap alone is not enough to claim a match to an existing OSV-Scanner occurrence.

The pre-public plan requires a caller-supplied local vulnerability DB and sets:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

It also requires Go telemetry mode already `off`. UPM will not alter the user's telemetry configuration to enable the provider.

There is intentionally **no subprocess executor yet**. Public promotion is blocked on a real local-DB govulncheck execution test, project-state mutation checks, honest representation of non-project cache/tool side effects, exact package/version/advisory correlation with existing UPM scan occurrences, shared project/fleet semantics, and a separate freshness/persistence model.

Because `GOSUMDB=off` is part of the no-network plan, this future provider must not claim that it freshly verifies dependency checksums. Symbol call-graph evidence and dependency-integrity evidence remain separate.

## Stronger reachability not claimed

UPM still has no public provider for:

- current-build-configuration reachability outside a future govulncheck-specific contract;
- vulnerable API/symbol reachability as a routed UPM command;
- runtime/data-flow reachability;
- exploitability determination.

Dependency paths and Go package-import paths must not be promoted into those stronger claims. The existence of pre-public govulncheck parsing/planning code does not change that public boundary.

## Exact advisory evidence contract

Project and fleet advisory flows retain and fingerprint the exact CycloneDX document scanned by OSV-Scanner. Native inventory is not rebuilt after scanning, successful scanner output without the exact scanned BOM is an evidence failure, and ordinary status never reruns scanner/providers merely to manufacture freshness.

## Local validation boundary

No GitHub Actions workflow is part of this project.

Aggregate local driver:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused drivers include:

```sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
sh ./scripts/test-sbom-project-components.sh
sh ./scripts/test-cache-provenance.sh
sh ./scripts/test-go-import-reachability.sh
sh ./scripts/test-go-symbol-reachability.sh
```

Focused reconstructed/local validation in this execution environment includes:

- Poetry/PDM reachability hardening: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5**;
- additional Cargo multi-crate checkout/noncanonical-object checks passed;
- cache provenance report semantics: **7/7**;
- separate cache identity-precision checks passed;
- Go package-import reachability core: **7/7**, including any-build-tag and replacement-aware logical/effective identity semantics;
- Go relationship execution environment: **3/3** reconstructed checks passed for `GOPROXY=off`, `GOWORK=off`, and unrelated-environment preservation;
- real local Go 1.23.2 source-query immutability: **1/1** isolated check passed with `go.mod` and `go.sum` unchanged;
- pre-public govulncheck parser/planner contract: **8/8** reconstructed checks passed for evidence-level separation, aliases/order, protocol/mode/level/local-DB refusal boundaries, message-shape validation, offline plan guards, and telemetry fail-closed behavior.

The project/fleet Go import-reachability CLI regressions are committed and included in local scripts, but they are not represented as having run end-to-end in this constrained runtime. The full private checkout still cannot be materialized here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
