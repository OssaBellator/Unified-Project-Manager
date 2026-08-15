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

## Go package-import advisory reachability

The first public stronger-than-dependency reachability layer is Go-only and explicit:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

The flag requires full `--native` inventory. It is not accepted with compatibility-only `--native-go`, because source evidence must be tied to vulnerable Go module impacts already correlated to the retained native scan inventory.

After an applied scan, UPM uses `go mod why -m` through the existing `GOPROXY=off` wrapper. Source-query states are explicit:

- `package-import-reachable`;
- `not-package-import-reachable`;
- `query-failed`.

Query failure is never converted to a successful negative. Multiple advisories for the same component/module share one source query.

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

### Execution/persistence boundary

Preview remains non-executing. Source queries run only after an applied native scan and only for vulnerable Go impacts.

The exact OSV-scanned CycloneDX document and scanner result keep their existing persisted evidence contract. Go package-import evidence is **report-only** and is not written into `.upm/audits/osv.json`; ordinary status does not replay it as durable evidence.

Source-query failure does not invalidate an otherwise valid OSV scan/evidence record because advisory scan validity and source/import enrichment are separate evidence layers.

See `REACHABILITY_EVIDENCE.md`.

## Stronger reachability not claimed

UPM still has no public provider for:

- current-build-configuration reachability;
- vulnerable API/symbol reachability;
- runtime/data-flow reachability;
- exploitability determination.

Dependency paths and Go package-import paths must not be promoted into those stronger claims.

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
```

Focused reconstructed/local validation in this execution environment includes:

- Poetry/PDM reachability hardening: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5**;
- additional Cargo multi-crate checkout/noncanonical-object checks passed;
- cache provenance report semantics: **7/7**;
- separate cache identity-precision checks passed;
- Go package-import reachability core: **6/6**, including the any-build-tag/current-build-not-evaluated evidence contract.

The project/fleet Go import-reachability CLI regressions are committed and included in local scripts, but they are not represented as having run end-to-end in this constrained runtime. The full private checkout still cannot be materialized here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
