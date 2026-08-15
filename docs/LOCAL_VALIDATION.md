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
sh ./scripts/test-yarn-execution-compat.sh
```

This focused local check verifies that the Berry provider does not inject the optional hardened-mode configuration while still forcing network refusal, telemetry suppression, immutable cache behavior, temporary install-state isolation, and the resolved Yarn executable path. The same regression is included in `scripts/test-yarn-native.sh`.

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
