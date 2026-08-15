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

These lock the shared network/telemetry/cache/install-state compatibility contract and older-Berry execution boundary. Both are included in `scripts/test-yarn-native.sh`.

## Poetry/PDM structured-lock providers

```sh
sh ./scripts/test-python-lock-native-validated.sh
```

The validated structured-lock slice covers provider validation, graph/reachability, manifest conditions, command-neutral queries, shared text rendering, path/search budgets, CycloneDX/SPDX uncertainty, retained native inventory, advisory correlation, and public provider routing.

Focused drivers also include:

```sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
sh ./scripts/test-python-lock-public-provider.sh
```

## All-provider fleet inventory and duplicate correlation

```sh
sh ./scripts/test-fleet-providers.sh
```

Fleet native inventory/duplicates route all eight public provider families while retaining provider-specific occurrence/certainty evidence and `reclaimable=false` duplicate semantics.

## Mixed-project SBOM topology

```sh
sh ./scripts/test-sbom-project-components.sh
```

The topology regression covers deterministic aggregate/component application anchors, clone-location-independent identity, provider-merge preservation, exact static-Poetry native inventory, and advisory counting that excludes topology-only anchors.

## Cache provenance

```sh
sh ./scripts/test-cache-provenance.sh
```

This focused driver runs:

- `tests/test_go_cache_provenance.py`;
- `tests/test_cargo_cache_provenance.py`;
- `tests/test_cache_provenance.py`.

The cache-provenance tests verify:

- Go attribution begins from native-reported module directories under `GOMODCACHE`;
- matching selected-version `.info`, `.mod`, `.zip`, and `.ziphash` download artifacts are derived only from the already-escaped physical module path;
- noncanonical Go cache paths fail closed instead of guessing download layout;
- Go build-cache bytes remain outside selected-module package attribution;
- Cargo registry objects are measured at `registry/src/<index>/<crate-version>`;
- Cargo git worktrees are measured once at `git/checkouts/<repo>/<revision>`, even when one checkout contains several crates;
- Cargo `registry/index`, `registry/cache`, `git/db`, workspace/path, and noncanonical locations are not mislabeled package-source attribution;
- legitimate multi-crate Cargo git checkout groups may contain several package identities without becoming conflicts;
- one Cargo registry source object mapped to several package identities is an explicit identity conflict;
- one Go physical path mapped to competing PURLs is an explicit identity conflict;
- `upm cache provenance` separates project-universe closure from native/storage observation completeness;
- missing projects, provider failures, uncovered applicable provider plans, inconsistent identities, or inconsistent byte measurements prevent a complete-observation claim;
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

No command above requires or invokes GitHub Actions.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Accordingly, full-suite claims remain conservative.

Focused reconstructed/local validation currently includes:

- Poetry/PDM reachability rewrite: **5/5** checks passed for conditional paths, direct ambiguity, transitive possible reachability, same-condition path multiplicity/path caps, and search-state truncation;
- separate structured-lock query/advisory consolidation and shared text-renderer checks passed;
- all-provider fleet core: **4/4** checks passed;
- mixed-project SBOM anchors: **5/5** checks passed;
- initial cache physical mapping: **5/5** reconstructed filesystem checks passed for Go escaped-path selected download artifacts, noncanonical-path refusal, inode-deduplicated measurement, Cargo source-root admission, and Cargo index/cache/db/local rejection;
- additional Cargo physical-object checks passed for multi-crate checkout-root grouping and noncanonical shallow checkout refusal;
- cache provenance report semantics: **7/7** reconstructed checks passed after adding physical identity inconsistency to manager totals/build-cache exclusion, no-reclaim invariants, closure invalidation, provider-failure separation, provider-skip incompleteness, and measurement inconsistency;
- separate identity-precision checks passed for legitimate multi-identity Cargo git containers, conflicting multi-identity Cargo registry objects, and competing Go PURLs on one physical path.

An earlier reconstructed structured-lock run exposed and led to a fix in `PythonLockPath.to_dict()`: nodes and markers are explicitly JSON-ready lists rather than tuple values that only became lists after `json.dumps`.

The committed focused drivers and aggregate `check-all-local-latest.sh` are intended for execution from a normal local clone where the complete private branch is available. They are not represented as having run end-to-end in this constrained runtime.

Some native-provider behavior is additionally validated against real locally available tools when present. When a manager/tool is unavailable, tests verify planning/parser contracts without silently downloading that manager during validation.
