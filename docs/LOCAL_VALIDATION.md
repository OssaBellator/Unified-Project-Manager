# Local-only validation

Unified Project Manager deliberately does not use GitHub Actions in this repository. Validation is designed to run from a local checkout with Python 3.11+.

## Baseline repository check

```sh
sh ./scripts/check.sh
```

This compiles the source/tests and runs the standard-library `unittest` suite through the repository's local scripts.

## Focused local drivers

```sh
sh ./scripts/test-integration.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
sh ./scripts/test-sbom-project-components.sh
sh ./scripts/test-cache-provenance.sh
sh ./scripts/test-go-import-reachability.sh
sh ./scripts/test-go-symbol-reachability.sh
```

No command above requires or invokes GitHub Actions.

## Go package-import advisory reachability

`scripts/test-go-import-reachability.sh` runs:

- `tests/test_go_offline_provider.py`;
- `tests/test_go_import_reachability.py`;
- `tests/test_go_import_reachability_audit.py`;
- `tests/test_go_mod_why_readonly.py`.

These cover positive/negative/query-failed import evidence, any-build-tag/test-import semantics, replacement logical/effective identities, `GOPROXY=off` + `GOWORK=off`, project/fleet routing, report-only persistence semantics, and a real-Go check that `go mod why -m` leaves `go.mod` and `go.sum` unchanged.

## Pre-public Go vulnerable-symbol groundwork

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

This driver validates lower-level govulncheck groundwork only. It does **not** make symbol reachability a public UPM capability.

It currently runs:

- `tests/test_go_symbol_reachability.py` — protocol/parser/local-plan contract;
- `tests/test_go_symbol_correlation.py` — strict correlation to existing UPM Go advisory impacts;
- `tests/test_go_symbol_public_boundary.py` — govulncheck remains outside the public provider registry;
- `tests/test_go_symbol_preflight.py` — executable/local-state/telemetry inspection without launching govulncheck;
- `tests/test_go_symbol_execution.py` — fail-closed subprocess execution boundary using injected process results.

### Parser/planner contract

The parser requires exact govulncheck protocol `v1.0.0`, explicit `source` + `symbol` mode, and a local `file://` vulnerability DB. Module/package/symbol findings remain distinct; only first-frame function/method findings become symbol evidence.

The offline plan sets:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

### Strict correlation

A symbol finding attaches to an existing UPM Go advisory impact only when all of these agree:

- exact component and `go-modules` provider;
- GO OSV ID or alias from that exact govulncheck OSV record;
- effective module identity;
- exact non-missing module version.

Replacement correlation uses the effective replacement module identity. Alias/module/version mismatch, missing version, cross-component/provider rows, and multiple competing UPM advisory identities fail closed. Duplicate exact dependency impacts consolidate paths.

### Read-only preflight

Preflight revalidates project/DB state, Go/govulncheck executables, and `go env GOTELEMETRY`. It never launches govulncheck and never changes telemetry configuration. Telemetry must already be exactly `off`.

### Fail-closed executor contract

The pre-public executor is now implemented but not publicly routed. Tests verify:

- unready or plan-mismatched preflight cannot launch;
- the preflight-resolved executable is used directly with no shell;
- the offline plan environment is preserved;
- JSON-mode exit 0 with symbol findings is a successful command execution;
- JSON-mode exit 0 with zero findings is also a successful command execution;
- any nonzero exit is execution failure and stdout is not accepted as valid evidence;
- malformed JSON is invalid evidence;
- reported DB URI must exactly equal the planned local DB URI;
- launch `OSError` is explicit;
- a ready preflight missing a resolved govulncheck executable is rejected.

The executor remains report-only/pre-public. Mocked execution tests do not prove real govulncheck project-state or cache side effects.

### Live execution blockers

A real govulncheck symbol execution is **not** claimed in this environment. Current state:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

None of those conditions were changed automatically: UPM did not install govulncheck, download a vulnerability DB, or alter telemetry settings.

See `GO_SYMBOL_REACHABILITY.md` for the remaining promotion gate.

## Comprehensive local run

```sh
sh ./scripts/check-all-local-latest.sh
```

This runs baseline, integration/provider, native-security, Yarn, validated Poetry/PDM, cache-provenance, and pre-public Go symbol slices.

## Validation completed in this constrained runtime

This implementation environment still cannot materialize the full private branch as one normal checkout. Full-suite claims therefore remain conservative.

Focused reconstructed/local validation currently includes:

- Poetry/PDM reachability: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5** plus additional Cargo object checks;
- cache provenance report semantics: **7/7** plus separate identity-precision checks;
- Go package-import reachability core: **7/7**;
- Go relationship execution environment: **3/3**;
- real local Go 1.23.2 source-query immutability: **1/1**;
- pre-public govulncheck parser/planner: **8/8**;
- strict govulncheck-to-UPM symbol correlation: **9/9**;
- govulncheck preflight: **6/6**;
- fail-closed govulncheck executor contract: **9/9**;
- live symbol preflight blockers independently confirmed without changing tool, DB, or telemetry state.

The committed drivers are intended for a normal local private checkout. The full aggregate is not represented as having run end-to-end in this constrained runtime.
