# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Follow-up/pre-public work must not be inferred as public capability.

## Public boundary

The public native-provider surface remains exactly Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Govulncheck is **not** public and has no CLI/provider route.

Public Go package-import reachability remains report-only, `GOPROXY=off` + `GOWORK=off`, replacement-aware, and weaker than symbol/runtime/exploitability evidence.

## Pre-public Go symbol stack

The branch contains six lower layers:

1. strict parser/planner;
2. exact advisory/module/version correlation;
3. read-only preflight;
4. fail-closed executor;
5. shared project/fleet reporting;
6. public-boundary regression.

### Executor review boundary

The executor launches only after a ready preflight for the exact same project and DB, uses the preflight-resolved executable directly, preserves the offline environment, and never retries online or mutates telemetry settings.

Govulncheck JSON exit code 0 means the command completed whether or not vulnerabilities exist; findings are read from validated JSON. Nonzero exit is failure and stdout is not accepted as valid symbol evidence.

Malformed protocol evidence, local-DB mismatch, preflight mismatch, missing resolved executable, or launch errors all fail explicitly.

### Correlation review boundary

Symbol attachment requires exact component/provider, GO OSV ID or alias from the exact govulncheck OSV record, effective module, and exact non-missing version. Alias overlap alone is insufficient. Replacement correlation uses effective replacement module identity while package-import querying retains the logical/original module namespace.

### Shared project/fleet reporting boundary

Project reports consume already-completed execution plus dependency impacts. Failed/blocked/invalid execution leaves `correlation=null`; UPM does not manufacture a negative symbol result.

Fleet aggregation does not rerun execution/correlation. It keeps independent counts for:

```text
execution_succeeded
execution_failed_or_blocked
symbol_findings
correlated_matches
unmatched_symbol_findings
```

This shared data model is pre-public groundwork, not a CLI route.

### Persistence/freshness boundary

Symbol evidence remains `persisted=false`. No source/build freshness fingerprint exists yet.

Do not reuse only `go.mod`/`go.sum`, the dependency graph, or the OSV-scanned SBOM as a call-graph freshness proxy: govulncheck source results depend on actual source/build configuration and can be affected by local replacements and source inputs outside such a narrow fingerprint.

### Side-effect/live-runtime boundary

```text
project mutation = none planned; real-runtime verification still required
non-project cache/tool mutation = possible
runtime reachability = not evaluated
exploitability = not established
```

The no-network plan includes `GOSUMDB=off`, so symbol analysis is not fresh integrity verification.

No real govulncheck scan is claimed in this environment: govulncheck is absent, telemetry is `local`, and no usable local DB was found. No install/download/settings mutation was performed.

## Remaining promotion gate

Do not add public symbol routing until:

- real local-DB execution passes preflight;
- project-state and cache/tool side effects are characterized;
- strict correlation is proven against real output;
- a conservative source/build-state fingerprint and symbol persistence/freshness model exist;
- ordinary status remains free of hidden symbol execution.

## Validation boundary

No GitHub Actions workflow is used. Focused reconstructed/local results include:

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

The full private branch still cannot be materialized/run end-to-end here.

## Merge hygiene

The branch contains many small contents-API commits. If/when merge is authorized, squash merge remains the appropriate default.

Do not merge this PR without explicit user authorization.
