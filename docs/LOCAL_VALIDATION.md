# Local-only validation

Unified Project Manager deliberately does not use GitHub Actions in this repository. Validation is designed to run from a local checkout with Python 3.11+.

## Local entrypoints

```sh
sh ./scripts/check.sh
sh ./scripts/test-integration.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-python-lock-native-validated.sh
sh ./scripts/test-fleet-providers.sh
sh ./scripts/test-sbom-project-components.sh
sh ./scripts/test-cache-provenance.sh
sh ./scripts/test-go-import-reachability.sh
sh ./scripts/test-go-symbol-reachability.sh
sh ./scripts/check-all-local-latest.sh
```

No command above invokes GitHub Actions.

## Public Go package-import reachability

The dedicated reachability driver covers `GOPROXY=off` + `GOWORK=off`, any-build-tag/test-import semantics, replacement logical/effective identities, positive/negative/query-failed states, project/fleet routing, report-only semantics, and a real local Go check proving `go mod why -m` leaves `go.mod`/`go.sum` unchanged.

## Pre-public Go vulnerable-symbol stack

`scripts/test-go-symbol-reachability.sh` now runs:

- `tests/test_go_symbol_reachability.py` — parser/planner;
- `tests/test_go_symbol_correlation.py` — strict correlation;
- `tests/test_go_symbol_public_boundary.py` — no public provider promotion;
- `tests/test_go_symbol_preflight.py` — read-only readiness inspection;
- `tests/test_go_symbol_execution.py` — fail-closed subprocess boundary;
- `tests/test_go_symbol_reporting.py` — shared project/fleet report model.

### Parser/planner

Requires protocol `v1.0.0`, source+symbol scan mode, local `file://` DB, and preserves module/package/symbol levels. The plan sets `GOPROXY=off`, `GOWORK=off`, `GOSUMDB=off`, and `GOTOOLCHAIN=local`.

### Strict correlation

Requires exact component/provider, advisory GO-ID/alias, effective module, and exact version. Replacement, mismatch, missing-version, ambiguity, and duplicate-path behavior are covered explicitly.

### Preflight

Revalidates project/DB/executables and `GOTELEMETRY=off` without launching govulncheck or mutating telemetry settings.

### Executor

Tests cover JSON-mode vulnerable/clean success, nonzero failure, malformed evidence, DB mismatch, preflight mismatch/blocking, launch errors, and missing resolved executable. The executor remains pre-public.

### Shared project/fleet reporting

Tests cover:

- successful execution + strict matched symbol;
- successful execution + explicit unmatched symbol;
- failed execution producing no fabricated negative correlation;
- deterministic fleet ordering;
- independent fleet counts for execution failures, raw symbol findings, correlated matches, and unmatched symbols;
- normalized project identity.

The reporting model does not execute or persist anything.

### Live runtime blocker

A real govulncheck symbol scan is not claimed here:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

No install, DB download, or telemetry mutation was performed.

## Focused reconstructed/local results

- Poetry/PDM reachability: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- cache physical mapping: **5/5** plus precision checks;
- cache report semantics: **7/7** plus identity checks;
- Go package-import reachability: **7/7**;
- Go relationship environment isolation: **3/3**;
- real local Go import-query immutability: **1/1**;
- govulncheck parser/planner: **8/8**;
- strict symbol correlation: **9/9**;
- govulncheck preflight: **6/6**;
- fail-closed govulncheck executor: **9/9**;
- shared project/fleet symbol reporting: **6/6**.

The full private branch still cannot be materialized and executed end-to-end in this constrained runtime. Committed local drivers are intended for a normal private checkout.
