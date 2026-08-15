# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. They are intentionally stricter than a feature checklist: anything listed as lower-level or follow-up should not be inferred as public capability.

## Public native providers

The public native-provider surface currently consists of:

- Go;
- npm;
- pnpm;
- Yarn Berry 2+;
- Cargo;
- uv.

Public graph/why/impact/fleet/SBOM/advisory behavior for those providers is documented in `NATIVE_PROVIDERS.md`.

Yarn Classic is not covered by the Berry provider.

## Yarn Berry review boundary

The Berry provider uses exact descriptor/locator resolution identity and preserves workspace/virtual package structure. Project install-state persistence is redirected to a temporary path, network is disabled inside Berry, and cache mutation is blocked.

SBOM/advisory identity is additionally scoped to locators reachable from active workspace/project roots. A stored Yarn package record that is not reachable from a workspace root is not promoted into CycloneDX/SPDX or advisory scan inventory merely because `yarn info --all --recursive` returned it.

### Compatibility cleanup resolved

The provider no longer forces `YARN_ENABLE_HARDENED_MODE`. Hardened mode was not part of the provider safety contract and forcing that configuration name could make otherwise-supported older Berry runtimes fail before graph reconstruction.

Execution and preview now share `yarn_execution_policy.py`, so the public preview states that hardened mode is `unchanged` rather than claiming UPM disables it. The required fail-closed controls remain unchanged: Berry network access is disabled, install state is redirected outside the project, telemetry is suppressed, and the cache is immutable. A runtime that cannot reconstruct the graph under those constraints still fails explicitly.

Focused regressions are available through:

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
```

and both are included in `scripts/test-yarn-native.sh`.

## Structured Poetry/PDM provider: implemented below the public line

A structured TOML provider exists for `poetry.lock` and `pdm.lock`, with focused local regressions, but it is intentionally not included in public provider coverage yet.

Implemented lower-level semantics include:

- static package/relationship ingestion with no subprocess/network/mutation;
- exact-one-candidate resolution only;
- explicit duplicate-name ambiguity;
- project-root dependency paths;
- marker/optional-aware conditional reachability;
- direct PEP 621 optional-group, Poetry optional-table, Poetry marker-table, optional Poetry-group, and Poetry multi-constraint conditions preserved before graph construction;
- reachable ambiguity reporting without fake paths;
- a shared command-neutral query contract for future `why`, `impact`, and fleet impact routing;
- registry-only PyPI PURL identity;
- reachable-only SBOM inventory with ambiguous candidates retained as possible scan inventory;
- separate conditional, ambiguous, unresolved, and non-registry omission semantics;
- conservative CycloneDX and SPDX relationships;
- contract validation that rejects unsupported dependency shapes or record-level package conditions.

`python_lock_provider.py` provides the pre-promotion orchestration boundary:

- provider ids `poetry-lock` and `pdm-lock`;
- shared `structured-lock-dependency-graph` scope;
- plan-based component ownership;
- validated execution as the high-level provider path;
- suppression of broad adapter `resolved_packages` for provider-owned components before a future native SBOM merge, preventing orphan/ambiguous static lock records from leaking back into certainty-aware inventory.

`python_lock_queries.py` is deliberately command-neutral. Future project `why`, project `impact`, and fleet impact integration should serialize the same certainty-aware query result rather than implementing three subtly different marker/optional/ambiguity policies.

`python_lock_native_inventory.py` now provides the exact advisory-side pre-promotion boundary: the exact CycloneDX document, validated provider plans, and the same `PythonLockGraphResult` objects are retained together. Assembly fails closed on provider failure or plan/result mismatch, preventing later advisory explanations from being rebuilt against different evidence.

Promotion remains gated on routing graph, why, impact, fleet impact, SBOM, audit, and provider status together. Until then, `provider_registry` must not claim Poetry/PDM native relationship coverage.

See `PYTHON_LOCK_PROVIDERS.md`.

## Exact advisory evidence contract

Project and fleet advisory flows share the same evidence rule:

- provider-backed inventory is constructed once for an applied native scan;
- the exact CycloneDX document given to OSV-Scanner is retained on the result;
- persisted evidence fingerprints that exact document;
- native inventory is not rebuilt after scanning;
- successful scanner output without the exact scanned BOM is an evidence failure rather than a silent success;
- fleet output distinguishes planning, native-inventory, scanner, and evidence failures;
- ordinary status never reruns scanner/providers to manufacture freshness.

The Poetry/PDM internal inventory object now matches this evidence shape, but it remains intentionally disconnected from public `audit --native` until project/fleet query routing and provider-status coverage can move with it.

## Local validation boundary

No GitHub Actions workflow is part of this project.

The latest aggregate local driver is:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused provider drivers include:

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
sh ./scripts/test-python-lock-native-validated.sh
```

Focused reconstructed/local validation in this execution environment currently includes:

- Yarn execution policy: **3 tests passed**;
- Yarn refactored Berry 2.x compatibility boundary: **1 test passed**;
- structured Python lock provider boundary: **3 tests passed**;
- structured Python lock SBOM uncertainty: **5 focused scenarios passed**;
- direct Python manifest-condition normalization: **5 focused scenarios passed**;
- shared structured Python query contract: **3 focused scenarios passed**;
- exact structured Python inventory assembly: **3 focused scenarios passed**.

The repository regression files contain additional assertions beyond those reconstructed slices. This execution environment still cannot materialize the entire private feature branch as one local checkout, so the latest full branch has not been executed end-to-end here. Keep whole-suite claims conservative until the branch is run from a normal local clone.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during this implementation session. If/when the user authorizes merge, a squash merge is the appropriate default to avoid importing that implementation transport history into `main`.

Do not merge this PR without explicit user authorization.
