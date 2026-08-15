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

The cache-provenance tests cover Go native physical module/download attribution, Cargo registry/git physical object grouping, explicit cache/object refusal boundaries, closure versus observation completeness, physical identity conflicts, and invariant no-reclaim semantics.

The provenance driver is included by `scripts/check-all-local-latest.sh`.

## Go package-import advisory reachability

```sh
sh ./scripts/test-go-import-reachability.sh
```

The dedicated driver runs:

- `tests/test_go_offline_provider.py`;
- `tests/test_go_import_reachability.py`;
- `tests/test_go_import_reachability_audit.py`;
- `tests/test_go_mod_why_readonly.py`.

These regressions cover:

- `package-import-reachable` when offline `go mod why -m` returns a package import path;
- explicit successful `not-package-import-reachable` instead of treating an empty path as failure;
- `query-failed` for command failure or provider skip, never converted to a clean negative;
- one query per component/logical-module pair even when several advisories refer to the same vulnerable module;
- non-Go dependency impacts never triggering Go source queries;
- Go's `why` graph being emitted explicitly as `build_constraints=any-tags`, with `current_build_configuration_reachability=not-evaluated` and `test_imports_may_contribute=true`;
- versioned Go replacements querying the logical required module path while retaining the effective replacement identity separately (`queried_module`, `effective_module`, `replacement_active`);
- component-scoped Go graph/why execution forcing both `GOPROXY=off` and `GOWORK=off` even when ambient values are set, while preserving unrelated environment variables;
- a real installed Go tool, when available, leaving `go.mod` and `go.sum` byte-for-byte unchanged after `go mod why -m` against an isolated local replacement;
- `--go-import-reachability` requiring full `--native` scan inventory rather than compatibility-only `--native-go`;
- preview remaining non-executing;
- project and fleet applied routing keeping source/import evidence separate from dependency impacts;
- source/import rows retaining `api_reachability=not-evaluated`, `runtime_reachability=not-evaluated`, `exploitability=not-established`, and `persisted=false`.

The same trust-boundary and reachability tests are included in `scripts/test-native-security.sh`, which is part of the aggregate local path. The real-Go test skips when the Go executable is unavailable; it never downloads a toolchain for validation.

## Pre-public Go vulnerable-symbol groundwork

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

This driver validates lower-level govulncheck groundwork only. It does **not** execute govulncheck and it does not make symbol reachability a public UPM capability.

It currently runs:

- `tests/test_go_symbol_reachability.py` — protocol/parser/local-plan contract;
- `tests/test_go_symbol_correlation.py` — strict correlation to existing UPM Go advisory impacts;
- `tests/test_go_symbol_public_boundary.py` — govulncheck remains outside the public relationship-provider registry;
- `tests/test_go_symbol_preflight.py` — executable/local-state/telemetry inspection without launching govulncheck.

The focused contract covers:

- exact govulncheck protocol `v1.0.0`;
- explicit `scan_mode=source` and `scan_level=symbol` requirements;
- local `file://` vulnerability database requirement;
- module-, package-, and symbol-level finding separation;
- only first-frame function/method findings being classified as called-symbol evidence;
- strict component + advisory id/alias + effective-module + exact-version correlation;
- Go replacement correlation using effective replacement module identity rather than the logical import namespace;
- alias/module/version mismatch, missing versions, cross-component/provider rows, and multi-advisory ambiguity failing closed;
- duplicate exact dependency impacts consolidating their dependency paths into one symbol match;
- offline plan guards `GOPROXY=off`, `GOWORK=off`, `GOSUMDB=off`, and `GOTOOLCHAIN=local`;
- read-only preflight revalidating project/DB state, both executables, and `go env GOTELEMETRY`;
- telemetry mode required to already be `off`; UPM does not mutate telemetry settings;
- govulncheck remaining absent from the eight-provider public registry.

The pre-public symbol driver is included by `scripts/check-all-local-latest.sh` so parser/correlation/preflight compatibility remains covered before execution is promoted.

A real govulncheck symbol execution is **not** claimed in this environment. The current runtime has no `govulncheck` executable, no usable local vulnerability database was found, and `go env GOTELEMETRY` reports `local` rather than the provider's required `off`. None of those conditions were changed automatically: UPM did not install govulncheck, download a vulnerability database, or alter the user's telemetry mode.

See `GO_SYMBOL_REACHABILITY.md` for the remaining public-promotion gate and side-effect/integrity boundaries.

## Native-security focused slice

```sh
sh ./scripts/test-native-security.sh
```

This concentrates on provider-backed CycloneDX advisory inventory, the OSV scan boundary, structured-lock advisory path/consolidation coverage, and public opt-in Go package-import reachability.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs the baseline check plus integration/provider, native-security, Yarn Berry, validated Poetry/PDM provider, cache-provenance, and pre-public Go symbol slices in sequence.

No command above requires or invokes GitHub Actions.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Accordingly, full-suite claims remain conservative.

Focused reconstructed/local validation currently includes:

- Poetry/PDM reachability rewrite: **5/5** checks passed;
- separate structured-lock query/advisory consolidation and shared text-renderer checks passed;
- all-provider fleet core: **4/4** checks passed;
- mixed-project SBOM anchors: **5/5** checks passed;
- initial cache physical mapping: **5/5** reconstructed filesystem checks passed;
- additional Cargo physical-object checks passed for multi-crate checkout-root grouping and noncanonical shallow checkout refusal;
- cache provenance report semantics: **7/7** reconstructed checks passed;
- separate cache identity-precision checks passed for legitimate multi-identity Cargo git containers, conflicting multi-identity Cargo registry objects, and competing Go PURLs on one physical path;
- Go package-import reachability core: **7/7** reconstructed checks passed for positive import reachability, replacement-aware logical/effective module identity, successful negative, query failure, provider skip, query deduplication, non-Go filtering, and the any-build-tag/current-build-not-evaluated evidence contract;
- Go relationship execution environment: **3/3** reconstructed checks passed for graph isolation, why isolation, and preservation of unrelated environment while overriding `GOPROXY`/`GOWORK`;
- real local Go 1.23.2 source-query immutability: **1/1** isolated check passed, with `go mod why -m` returning the expected path while `go.mod` and `go.sum` remained byte-for-byte unchanged;
- pre-public govulncheck parser/planner contract: **8/8** reconstructed checks passed;
- strict govulncheck-to-UPM symbol correlation: **9/9** reconstructed checks passed;
- govulncheck executable/local-state/telemetry preflight: **6/6** reconstructed checks passed;
- live preflight blockers independently confirmed: Go is `/usr/local/go/bin/go`, telemetry is `local`, govulncheck is absent, and no candidate local vulnerability DB was found.

The project/fleet Go import-reachability CLI regressions and pre-public symbol test driver are committed and included in local scripts, but the private branch is not represented as having run end-to-end in this constrained runtime.

The committed focused drivers and aggregate `check-all-local-latest.sh` are intended for execution from a normal local clone where the complete private branch is available. They are not represented as having run end-to-end here.

Some native-provider behavior is additionally validated against real locally available tools when present. When a manager/tool is unavailable, tests verify planning/parser contracts without silently downloading that manager during validation.
