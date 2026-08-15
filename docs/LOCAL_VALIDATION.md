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

This exercises higher-risk cross-layer contracts including workspace-aware mutation routing, receipts, native provider routing, native SBOM integration, workspace ownership/health, local evidence/status behavior, and advisory evidence boundaries.

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

It now includes the public provider promotion regression in addition to the lower-level certainty/validation tests.

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

Together these cover:

- public `poetry-lock` / `pdm-lock` provider ids and `structured-lock-dependency-graph` scope;
- provider coverage/status registration;
- supported lock-contract validation with fail-closed unsupported semantics;
- direct optional, marker, Poetry-group, and multi-constraint propagation from `pyproject.toml`;
- one certainty-aware query contract used by `why`, project impact, and fleet impact;
- resolved conditional paths and condition-preserving ambiguity paths ending at explicit `?dependency` hops;
- reachable-only CycloneDX/SPDX inventory;
- possible scan inventory for reachable ambiguous candidates without fabricated dependency edges;
- separate conditional, ambiguous, unresolved, and non-registry omission evidence;
- exact native CycloneDX inventory retaining the same Poetry/PDM graph results for advisory correlation;
- public graph, why, impact, SBOM, and advisory route integration.

## Native-security focused slice

```sh
sh ./scripts/test-native-security.sh
```

This concentrates on provider-backed CycloneDX advisory inventory and the OSV scan boundary. Poetry/PDM now participate through the same retained native inventory object as the other public providers.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs the baseline check plus integration/provider, native-security, Yarn Berry, and validated Poetry/PDM provider slices in sequence.

No command above requires or invokes GitHub Actions. Native relationship tests use mocks/fixtures where executing an external package manager is not part of the test contract; provider execution tests assert exact resolved executable paths and explicit network/mutation guarantees.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Accordingly, full-suite claims remain conservative.

A reconstructed current Poetry/PDM promotion-core slice was executed locally and passed **3/3** after fixing a serializer mismatch discovered by that run. It covered:

- resolved marker-conditional structured-lock reachability;
- ambiguity paths retaining marker and optional-edge conditions;
- OSV correlation for both resolved packages and ambiguity-only candidate findings.

The reconstructed run also exposed and led to a fix in `PythonLockPath.to_dict()`: nodes and markers are now explicitly JSON-ready lists rather than tuple values that only became lists after `json.dumps`.

The committed `test-python-lock-public-provider.sh` and aggregate `check-all-local-latest.sh` are intended for execution from a normal local clone where the complete private branch is available. They are not represented as having run end-to-end in this constrained runtime.

Some native-provider behavior is additionally validated against real locally available tools when present (for example npm). When a manager/tool is unavailable, tests verify planning/parser contracts without silently downloading that manager during validation.
