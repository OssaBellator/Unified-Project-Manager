# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Anything described as follow-up should not be inferred as implemented public capability.

## Public native providers

The public native-provider surface consists of:

- Go;
- npm;
- pnpm;
- Yarn Berry 2+;
- Cargo;
- uv;
- Poetry;
- PDM.

Public graph/why/impact/fleet/SBOM/advisory behavior is documented in `NATIVE_PROVIDERS.md`. Poetry/PDM's structured-lock uncertainty contract is detailed in `PYTHON_LOCK_PROVIDERS.md`.

Yarn Classic remains outside the Berry provider.

## Yarn Berry boundary

The Berry provider preserves exact descriptor/locator and workspace/virtual identity. Network access is disabled inside Berry, install state is redirected outside the project, telemetry is suppressed, and supported cache mutation is blocked.

The provider does not force `YARN_ENABLE_HARDENED_MODE`; execution and preview share `yarn_execution_policy.py`, and preview reports hardened mode as `unchanged`.

SBOM/advisory/fleet inventory includes only locators reachable from active project/workspace roots. Stored but inactive Yarn records are not promoted merely because `yarn info --all --recursive` returned them.

## Poetry/PDM public uncertainty model

Poetry/PDM are public as `poetry-lock` and `pdm-lock`, sharing `structured-lock-dependency-graph` scope.

Public routing includes graph, why, project/fleet impact, CycloneDX/SPDX, project/fleet advisory, provider status, and fleet native inventory/duplicate correlation.

The shared reachability model:

- distinguishes resolved `packages` from ambiguity-derived `possible_packages`;
- renders every unresolved hop as `?dependency`;
- conservatively traverses all ambiguous candidates and propagates possible state through descendants;
- preserves marker/optional conditions and ambiguity-hop count on every path;
- preserves distinct same-condition parent paths;
- uses explicit path/search budgets (`64` paths per package, `10000` traversal states by default);
- surfaces `paths_truncated` / `search_truncated` rather than hiding incomplete explanations;
- shares one text renderer across why/project impact/fleet impact.

Advisory correlation reuses the same validated structured-lock result that produced the exact scanned BOM. Direct or transitive ambiguity-derived findings are labeled `possible-via-ambiguous-lock-reference`. If one locked package occurrence has both a resolved path and a possible alternative path, UPM emits one consolidated advisory impact containing both path classes.

Unsupported lock relationship shapes or package-record-level conditions remain explicit provider failures.

## All-provider fleet inventory

`projects inventory --native` and `projects duplicates --native` cover all eight public provider families.

Provider-specific occurrence evidence is preserved. In particular, pnpm retains workspace/alias/scope/depth/directness/dedupe metadata, Yarn uses active-root-reachable locators only, and Poetry/PDM use certainty-aware `unconditional` / `conditional` / `possible` rows while excluding orphan lock records.

Cross-project duplicate groups remain observation-only. `reclaimable=false` is explicit.

## Mixed-project SBOM topology

Aggregate SBOMs include a deterministic project topology layer; see `SBOM_PROJECT_COMPONENTS.md`.

CycloneDX uses one aggregate application root plus one application anchor per discovered component. SPDX mirrors that model with aggregate/component `APPLICATION` packages and aggregate `CONTAINS` relationships.

Anchor identity and aggregate naming are clone-location-independent. The topology layer deliberately does **not** manufacture component→package edges from generic normalized inventory. Native/provider relationship evidence remains authoritative.

Provider merge regressions cover Go/npm/pnpm/Yarn/Poetry-PDM CycloneDX/SPDX paths and a full static Poetry native inventory pipeline. Application anchors remain topology-only and do not inflate advisory package counts.

## Public cache provenance boundary

`upm cache provenance` is now public for Go and Cargo physical attribution over explicitly registered projects.

```sh
upm cache provenance
upm cache provenance --manager go
upm cache provenance --manager cargo
upm cache provenance --closed-universe --json
```

This is an observation command, not a cleanup planner.

### Go

Go physical identity starts from the selected module directory returned by the offline native graph. UPM does not recreate Go's module-cache escaping from logical package names.

When the native directory has canonical escaped `name@version` form, UPM reuses that physical path to attribute existing selected-version `.info`, `.mod`, `.zip`, and `.ziphash` files under `GOMODCACHE/cache/download`. Lock/list metadata and other versions are not attributed to that selected occurrence.

Noncanonical physical paths fail closed for download-artifact mapping. `GOCACHE` build bytes remain outside selected-module package attribution.

### Cargo

Cargo physical source identity starts from `manifest_path` returned by `cargo metadata --locked --offline`.

Attribution is restricted to exact source/check-out roots:

- `CARGO_HOME/registry/src`;
- `CARGO_HOME/git/checkouts`.

`registry/index`, `registry/cache`, `git/db`, workspace/path dependencies, and unrelated directories are not package-source attribution simply because they live below `CARGO_HOME`.

### Closure and reclaim semantics

The optional `--closed-universe` flag is an explicit user assertion that the registered project list represents the complete relevant project universe. Missing/unreadable registered projects invalidate that assertion.

Project-universe closure is separate from `observation_complete`: native/storage failures, applicable provider coverage gaps, missing/ambiguous cache roots, or inconsistent physical byte measurements make the observation incomplete even when the project registry itself is asserted closed.

The safety fields remain unconditional:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv physical package-cache provenance remains deliberately unsupported instead of heuristically reverse-engineering opaque cache/store layouts merely to claim coverage.

## Exact advisory evidence contract

Project and fleet advisory flows share the same rule:

- provider-backed inventory is constructed once for an applied native scan;
- the exact CycloneDX document given to OSV-Scanner is retained;
- persisted evidence fingerprints that exact document;
- native inventory is not rebuilt after scanning;
- successful scanner output without the exact scanned BOM is an evidence failure;
- ordinary status never reruns scanner/providers merely to manufacture freshness.

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
- cache physical mapping: **5/5**;
- cache provenance report semantics: **6/6**;
- separate structured-lock advisory consolidation/text-rendering checks;
- previously recorded Yarn/provider/security slices.

The cache mapping slice covers native escaped Go selected-download mapping/noncanonical refusal/inode accounting and Cargo exact source-root admission versus index/cache/db/local rejection. The report-semantics slice covers manager totals/build-cache exclusion, no-reclaim invariants, closure invalidation, provider failure/skip incompleteness, and measurement inconsistency.

The committed full regressions include additional public command routing and locked-provider coverage checks. This execution environment still cannot materialize the entire private branch as one checkout, so the full aggregate is not claimed as executed here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
