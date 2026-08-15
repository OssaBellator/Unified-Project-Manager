# Local-only validation

Unified Project Manager deliberately does not use GitHub Actions in this repository. Validation is designed to run from a local checkout with Python 3.11+.

## Baseline repository check

```sh
sh ./scripts/check.sh
```

This compiles the source/tests and runs the standard-library `unittest` suite through the repository's existing local scripts.

## Integration/provider regression slice

```sh
sh ./scripts/test-integration.sh
```

This exercises the higher-risk cross-layer contracts added during the control-plane implementation, including:

- workspace-aware batch mutation routing;
- automatic mutation receipts and receipt validation;
- npm/pnpm/Cargo/Go/uv relationship-provider routing;
- npm/pnpm native SBOM integration;
- Cargo workspace ownership/health;
- local evidence/status behavior;
- security/advisory evidence boundaries.

## Yarn Berry execution compatibility

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
```

The policy check locks the shared environment/preview contract: network disabled, telemetry disabled, immutable cache, temporary install-state semantics, and hardened mode left unchanged. The compatibility check exercises the provider call boundary with an older Berry 2.x-style runtime and verifies the resolved executable path plus temporary state cleanup. Both are included in `scripts/test-yarn-native.sh`.

## Structured Poetry/PDM provider boundary

The comprehensive pre-promotion slice is:

```sh
sh ./scripts/test-python-lock-native-validated.sh
```

Focused drivers are also available for the individual contracts:

```sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
```

These checks cover the internal Poetry/PDM provider ids/scope, plan-based ownership, suppression of broad adapter `resolved_packages`, supported lock-contract validation, direct optional/marker propagation from `pyproject.toml`, certainty-aware query semantics shared by future `why`/`impact`/fleet routing, path multiplicity, and conservative CycloneDX/SPDX uncertainty behavior.

Poetry/PDM remain below the public native-provider line until graph, why, impact, fleet impact, SBOM, advisory inventory/path correlation, and provider-status coverage can be integrated atomically with the same certainty model.

## Native-security focused slice

```sh
sh ./scripts/test-native-security.sh
```

This concentrates on provider-backed CycloneDX advisory inventory and the OSV scan boundary.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs the baseline check plus the current integration/provider, native-security, Yarn Berry, and validated Python lock-provider slices in sequence.

No command above requires or invokes GitHub Actions. Native relationship tests use mocks/fixtures where executing an external package manager is not part of the test contract; provider execution tests assert exact resolved executable paths and explicit network/mutation guarantees.

Some native-provider behaviors are also validated against locally available real tools when the development environment includes them (for example npm). When a manager/tool is unavailable locally, UPM's tests should verify the planning/parser contract without silently downloading that manager during validation.
