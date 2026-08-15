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

`upm cache provenance` is public for Go and Cargo physical attribution over explicitly registered projects:

```sh
upm cache provenance
upm cache provenance --manager go
upm cache provenance --manager cargo
upm cache provenance --closed-universe --json
```

This is an observation command, not a cleanup planner.

### Go

Go physical identity starts from selected module directories returned by the offline native graph. UPM does not recreate Go module-cache escaping from logical names.

When a native directory has canonical escaped `name@version` form, UPM reuses that physical spelling to attribute existing selected-version `.info`, `.mod`, `.zip`, and `.ziphash` files under `GOMODCACHE/cache/download`. Lock/list metadata and other versions are excluded. Noncanonical physical paths fail closed. `GOCACHE` remains outside selected-module package attribution.

### Cargo physical-object model

Cargo physical identity starts from `manifest_path` returned by `cargo metadata --locked --offline` and is normalized to one canonical physical source object:

```text
CARGO_HOME/registry/src/<index>/<crate-version>
CARGO_HOME/git/checkouts/<repo>/<revision>
```

This avoids recursive overlap when a Cargo git checkout contains several crates. One git checkout group may therefore legitimately contain several native Cargo package identities and is measured once.

Registry source objects are different: one unpacked registry source object is expected to identify one package. Multiple package identities for one registry object are an explicit identity conflict.

`registry/index`, `registry/cache`, `git/db`, workspace/path dependencies, shallow noncanonical source objects, and unrelated directories remain outside package-source attribution.

### Closure, consistency, and reclaim semantics

`--closed-universe` is an explicit user assertion that the registered project list is the complete relevant project universe. Missing/unreadable registered projects invalidate that assertion.

Project-universe closure is separate from `observation_complete`. Native/storage failures, applicable provider gaps, missing/ambiguous cache roots, byte-accounting inconsistencies, competing Go PURLs for one physical path, multi-identity Cargo registry objects, or incompatible groups for one physical path make the observation incomplete.

Legitimate multi-crate Cargo git containers do **not** count as identity conflicts.

The safety fields remain unconditional:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv physical package-cache provenance remains deliberately unsupported instead of heuristically reverse-engineering opaque cache/store layouts merely to claim coverage.

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
```

Focused reconstructed/local validation in this execution environment includes:

- Poetry/PDM reachability hardening: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5**;
- additional Cargo multi-crate checkout/noncanonical-object checks passed;
- cache provenance report semantics: **7/7**;
- separate identity-precision checks passed for legitimate multi-package Cargo git containers, conflicting Cargo registry source identities, and competing Go PURLs on one physical path;
- previously recorded Yarn/provider/security slices.

The committed full regressions include public cache-provenance routing, locked-provider coverage checks, and the richer Cargo physical-object model. This execution environment still cannot materialize the entire private branch as one checkout, so the full aggregate is not claimed as executed here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
