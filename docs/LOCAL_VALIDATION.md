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

Together these cover:

- public `poetry-lock` / `pdm-lock` provider ids and `structured-lock-dependency-graph` scope;
- provider coverage/status registration;
- supported lock-contract validation with fail-closed unsupported semantics;
- direct optional, marker, Poetry-group, and multi-constraint propagation from `pyproject.toml`;
- one certainty-aware query contract used by `why`, project impact, fleet impact, and advisory correlation;
- resolved conditional paths and explicit ambiguity paths ending at `?dependency` hops;
- separate `possible_packages` that propagate through all ambiguous candidate descendants without claiming an environment-selected branch;
- distinct same-condition path multiplicity rather than node/condition collapsing;
- explicit `max_paths_per_package` and `max_search_states` budgets with visible `paths_truncated` / `search_truncated` evidence;
- shared text rendering for possible-only paths and truncation warnings;
- reachable-only CycloneDX/SPDX inventory with possible ambiguous scan inventory but no fabricated unconditional relationships;
- separate conditional, ambiguous, unresolved, and non-registry omission evidence;
- exact native CycloneDX inventory retaining the same Poetry/PDM graph results for advisory correlation;
- advisory consolidation when one locked package occurrence has both resolved and ambiguity-derived alternative paths;
- public graph, why, impact, SBOM, provider-status, and advisory route integration.

## Native-security focused slice

```sh
sh ./scripts/test-native-security.sh
```

This concentrates on provider-backed CycloneDX advisory inventory and the OSV scan boundary. It now includes `test_python_lock_security_impact.py`, which verifies transitive possible findings and resolved/possible path consolidation for Poetry/PDM.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs the baseline check plus integration/provider, native-security, Yarn Berry, and validated Poetry/PDM provider slices in sequence.

No command above requires or invokes GitHub Actions. Native relationship tests use mocks/fixtures where executing an external package manager is not part of the test contract; provider execution tests assert exact resolved executable paths and explicit network/mutation guarantees.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Accordingly, full-suite claims remain conservative.

The current reconstructed structured-lock reachability rewrite passed **5/5** focused tests covering:

- resolved marker/optional conditional paths;
- direct ambiguity with explicit candidate paths;
- transitive possible reachability below an ambiguous candidate;
- preservation of distinct same-condition parent paths plus per-package path caps;
- search-state budget truncation.

Separate reconstructed checks also passed for:

- the command-neutral query/advisory contract on a transitive possible package, retaining the full `?dependency` candidate path;
- advisory consolidation where one package occurrence has both a definite resolved path and an additional ambiguity-derived possible path;
- the shared possible-path text renderer.

An earlier reconstructed run exposed and led to a fix in `PythonLockPath.to_dict()`: nodes and markers are explicitly JSON-ready lists rather than tuple values that only became lists after `json.dumps`.

The committed `test-python-lock-public-provider.sh` and aggregate `check-all-local-latest.sh` are intended for execution from a normal local clone where the complete private branch is available. They are not represented as having run end-to-end in this constrained runtime.

Some native-provider behavior is additionally validated against real locally available tools when present (for example npm). When a manager/tool is unavailable, tests verify planning/parser contracts without silently downloading that manager during validation.
