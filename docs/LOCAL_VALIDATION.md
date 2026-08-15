# Local-only validation

Unified Project Manager deliberately does not use GitHub Actions in this repository. Validation is designed to run from a local checkout with Python 3.11+.

## Baseline repository check

```sh
sh ./scripts/check.sh
```

This compiles the source/tests and runs the standard-library `unittest` suite through the repository's local scripts.

## Integration/provider regression slice

```sh
sh ./scripts/test-integration.sh
```

This exercises higher-risk cross-layer contracts including workspace-aware mutation routing, receipts, native provider routing, native SBOM integration, workspace ownership/health, all-provider fleet inventory/duplicates, local evidence/status behavior, and advisory evidence boundaries.

## Yarn Berry execution compatibility

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
```

The policy check locks the shared environment/preview contract: network disabled, telemetry disabled, immutable cache, temporary install-state semantics, and hardened mode left unchanged. The compatibility check exercises the provider call boundary with an older Berry 2.x-style runtime and verifies the resolved executable path plus temporary state cleanup. Both are included in `scripts/test-yarn-native.sh`.

## Poetry/PDM structured-lock providers

The comprehensive Poetry/PDM slice is:

```sh
sh ./scripts/test-python-lock-native-validated.sh
```

It includes provider-boundary/validation, graph/reachability, direct-condition handling, command-neutral queries, shared text rendering, path multiplicity/budgets, CycloneDX/SPDX uncertainty, retained native inventory, advisory correlation, and public provider routing.

The dedicated public route check is:

```sh
sh ./scripts/test-python-lock-public-provider.sh
```

Focused drivers remain available for individual contracts:

```sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
```

Together these cover resolved/conditional/possible structured-lock paths, explicit ambiguity hops, transitive possible branches, path/search budgets, reachable-only SBOM inventory, advisory consolidation, and fail-closed unsupported lock semantics.

## All-provider fleet inventory and duplicate correlation

```sh
sh ./scripts/test-fleet-providers.sh
```

Fleet native inventory/duplicates route all eight public provider families.

The focused fleet regression verifies:

- Poetry/PDM use the same normalized Python package identity across managers;
- Poetry/PDM fleet rows use certainty-aware reachable structured-lock inventory and exclude orphan lock records;
- ambiguity-derived Poetry/PDM candidates are labeled `possible` rather than definite;
- pnpm retains workspace project, alias, dependency scope, depth/directness, and dedupe metadata;
- Yarn inventory excludes project roots and inactive stored locators by reusing active-root reachability;
- duplicate groups retain certainty states and remain observation-only (`reclaimable=false`).

## Mixed-project SBOM topology

```sh
sh ./scripts/test-sbom-project-components.sh
```

The committed topology regression covers deterministic aggregate/component application anchors, clone-location-independent identity, provider-merge preservation, exact static-Poetry native inventory, and advisory counting that excludes topology-only anchors.

## Cache provenance

```sh
sh ./scripts/test-cache-provenance.sh
```

This focused driver runs:

- `tests/test_go_cache_provenance.py`;
- `tests/test_cargo_cache_provenance.py`;
- `tests/test_cache_provenance.py`.

The cache-provenance tests verify:

- Go attribution begins from a native-reported module directory under `GOMODCACHE`;
- matching selected-version `.info`, `.mod`, `.zip`, and `.ziphash` download artifacts are derived only from that already-escaped physical directory, never from UPM re-encoding a logical module path;
- noncanonical Go cache paths fail closed instead of guessing download layout;
- Go build-cache bytes remain outside selected-module package attribution;
- Cargo physical package attribution is restricted to `CARGO_HOME/registry/src` and `CARGO_HOME/git/checkouts`;
- Cargo `registry/index`, `registry/cache`, `git/db`, workspace/path, and unrelated locations are not mislabeled package-source attribution;
- `upm cache provenance` separates project-universe closure from native/storage observation completeness;
- missing projects, provider failures, uncovered applicable provider plans, or inconsistent byte measurements prevent a complete-observation claim;
- `unattributed_means_unused=false`, `reclaimable_bytes=null`, and `reclaimable=false` remain invariant.

The provenance driver is included by `scripts/check-all-local-latest.sh`.

## Native-security focused slice

```sh
sh ./scripts/test-native-security.sh
```

This concentrates on provider-backed CycloneDX advisory inventory and the OSV scan boundary, including structured-lock advisory path/consolidation coverage.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs the baseline check plus integration/provider, native-security, Yarn Berry, validated Poetry/PDM provider, and cache-provenance slices in sequence.

No command above requires or invokes GitHub Actions. Native relationship tests use mocks/fixtures where executing an external package manager is not part of the test contract; provider execution tests assert exact resolved executable paths and explicit network/mutation guarantees.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Accordingly, full-suite claims remain conservative.

Focused reconstructed/local validation currently includes:

- Poetry/PDM reachability rewrite: **5/5** checks passed for conditional paths, direct ambiguity, transitive possible reachability, same-condition path multiplicity/path caps, and search-state truncation;
- separate structured-lock query/advisory consolidation and shared text-renderer checks passed;
- all-provider fleet core: **4/4** checks passed for cross-provider Python normalization, structured-lock certainty/orphan exclusion/possible propagation, and reachable-only Yarn scoping;
- mixed-project SBOM anchors: **5/5** checks passed for clone-stable refs/naming, CycloneDX topology, SPDX containment/namespace stability, and advisory counting that excludes topology anchors;
- cache physical mapping: **5/5** reconstructed filesystem checks passed for Go escaped-path selected download artifacts, noncanonical-path refusal, inode-deduplicated measurement, Cargo source-root admission, and Cargo index/cache/db/local rejection;
- cache report semantics: **6/6** reconstructed checks passed for manager totals/build-cache exclusion, no-reclaim invariants, closure invalidation, provider-failure separation, provider-skip incompleteness, and measurement inconsistency detection.

An earlier reconstructed structured-lock run exposed and led to a fix in `PythonLockPath.to_dict()`: nodes and markers are explicitly JSON-ready lists rather than tuple values that only became lists after `json.dumps`.

The committed focused drivers and aggregate `check-all-local-latest.sh` are intended for execution from a normal local clone where the complete private branch is available. They are not represented as having run end-to-end in this constrained runtime.

Some native-provider behavior is additionally validated against real locally available tools when present (for example npm). When a manager/tool is unavailable, tests verify planning/parser contracts without silently downloading that manager during validation.
