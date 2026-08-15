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

`scripts/test-go-symbol-reachability.sh` runs parser/planner, strict correlation, public-boundary, preflight, executor, project/fleet reporting, deterministic DB/runtime fixtures, and an optional real govulncheck end-to-end test.

The deterministic fixture support is:

- `tests/support_go_vulndb_fixture.py` — writes only the published Go vulnerability DB v1 filesystem endpoints;
- `tests/support_go_symbol_runtime_fixture.py` — writes a tiny app, versioned dependency file proxy, isolated Go caches, and the local vulnerability DB;
- `scripts/prepare-go-symbol-validation-fixture.sh DESTINATION` — creates/prepares that fully local fixture for manual validation.

### Fully local versioned dependency

The fixture uses `example.com/dep@v1.2.3` with no `replace`. Setup runs `go mod download` against only the generated `file://` module proxy, with `GOSUMDB=off` and isolated caches. The actual analysis environment then uses `GOPROXY=off`.

A real installed Go 1.23.2 check already confirms the versioned dependency remains resolvable after that transition.

### Optional real govulncheck test

`tests/test_go_symbol_real_runtime.py` skips unless:

- `go` already exists;
- `govulncheck` already exists;
- `go env GOTELEMETRY` is already exactly `off`.

It never installs govulncheck and never changes telemetry. When runnable, it generates the local DB/proxy/caches, snapshots the project after fixture setup, executes the UPM preflight/executor/correlation/report path, requires the synthetic `GO-2099-0001` / `Danger` symbol finding, and requires the project snapshot to remain byte-for-byte identical.

### Current live blocker

The DB and versioned dependency source are no longer external blockers because the repo generates them deterministically. A real govulncheck symbol scan is still not claimed here because:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
```

No install or telemetry mutation was performed to bypass those conditions.

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
- shared project/fleet symbol reporting: **6/6**;
- deterministic Go vulnerability-DB fixture: **7/7**;
- fully local versioned runtime fixture: **5/5**, including real Go file-proxy → offline-cache resolution;
- optional real govulncheck end-to-end regression: **committed but skipped in this environment** because prerequisites are not satisfied.

The full private branch still cannot be materialized and executed end-to-end in this constrained runtime. Committed local drivers are intended for a normal private checkout.
