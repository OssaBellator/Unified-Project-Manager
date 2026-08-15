# Go symbol reachability

This document describes a **pre-public** provider boundary for Go vulnerable-symbol reachability. It is not routed through `upm audit`, provider status, or any other public command yet.

## Evidence ladder

```text
dependency graph < package import graph < vulnerable symbol/call graph
```

Govulncheck source mode can supply static vulnerable-symbol call-graph evidence. That remains weaker than runtime/data-flow reachability or exploitability.

## Current pre-public stack

The branch now contains:

1. strict govulncheck v1 source/symbol/local-DB parser/planner;
2. strict correlation to existing UPM Go advisory impacts;
3. read-only executable/local-state/telemetry preflight;
4. fail-closed subprocess executor gated by the exact preflight;
5. one shared project/fleet reporting model over already-built execution/correlation results;
6. a public-boundary regression keeping govulncheck out of the eight-provider registry.

There is still **no public CLI flag/provider route and no persisted symbol evidence**.

## JSON evidence contract

Accepted streams must explicitly report:

```text
protocol_version = v1.0.0
scan_mode = source
scan_level = symbol
db = file://...
```

Module-, package-, and symbol-level findings remain separate. Only a finding whose first trace frame contains a function/method is classified as vulnerable-symbol/call-graph evidence.

## Strict correlation

A symbol finding attaches to an existing UPM Go advisory impact only when these agree:

- exact component and `go-modules` provider;
- GO OSV ID or alias from that exact govulncheck OSV record;
- effective module identity;
- exact non-missing module version.

Mismatch, missing version, or competing advisory identities stays unmatched with an explicit reason. Duplicate exact UPM impacts consolidate dependency paths.

For Go replacements, import-query identity and symbol-correlation identity intentionally differ:

```text
package-import query = logical/original module namespace
symbol correlation   = effective replacement module identity
```

## Offline plan and preflight

Planned command:

```text
govulncheck -format json -mode source -scan symbol -db file:///... ./...
```

Environment:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

Preflight revalidates project, DB, Go/govulncheck executables, and `go env GOTELEMETRY == off`. It never launches govulncheck or changes telemetry settings.

## Fail-closed executor

Execution is allowed only when the ready preflight belongs to the exact project and DB in the plan. The executor invokes the preflight-resolved executable directly, uses the offline environment, never retries online, and rejects nonzero exits, malformed JSON, or reported-DB mismatch.

Govulncheck JSON mode returns exit 0 regardless of whether vulnerabilities are detected, so UPM derives symbol findings from validated JSON rather than process status:

```text
0       = command completed; inspect report
nonzero = execution failure; stdout is not valid symbol evidence
```

The executor remains pre-public/report-only and explicitly says real-runtime project/cache side effects still need validation.

## Shared project/fleet reporting

`build_go_symbol_project_report(...)` consumes an already-completed execution plus existing dependency impacts. It never launches govulncheck.

- valid successful execution -> strict correlation is produced;
- successful execution with a symbol that cannot be correlated -> unmatched symbol remains explicit;
- blocked/failed/invalid execution -> `correlation = null`; UPM does **not** manufacture an empty/negative symbol-reachability result.

`build_go_symbol_fleet_report(...)` only aggregates already-built project reports and orders them deterministically. Fleet summary keeps these independent counts:

```text
execution_succeeded
execution_failed_or_blocked
symbol_findings
correlated_matches
unmatched_symbol_findings
```

This prevents a provider failure, an uncorrelated symbol, and a proven correlated symbol from collapsing into one boolean.

Both project and fleet representations remain:

```text
public = false
persisted = false
runtime_reachability = not-evaluated
exploitability = not-established
```

## Persistence/freshness boundary

Persistence is intentionally **not implemented yet**.

A safe symbol-evidence freshness contract cannot be based only on `go.mod`/`go.sum` or the OSV-scanned SBOM. Govulncheck source analysis depends on the actual build/source configuration; local replacements and source files outside a single simplistic manifest fingerprint can change call-graph results.

UPM will not create a persisted symbol-evidence format until the real-runtime execution boundary is validated and the source/build-state fingerprint can conservatively represent what govulncheck actually analyzed.

Ordinary status therefore remains free of hidden symbol analysis and has no symbol freshness state to replay.

## Side-effect and interpretation boundary

```text
project mutation = none planned; real-runtime verification still required
non-project cache/tool mutation = possible
fresh checksum verification = not claimed (`GOSUMDB=off`)
reclaimability inference = none
```

Static symbol evidence does not establish production execution, attacker-controlled data flow, complete reflection/unsafe modeling, or exploitability.

## Public boundary

Govulncheck remains absent from the eight-provider public registry. No `--go-symbol-reachability` flag exists.

## Validation

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

Focused reconstructed/local evidence:

- parser/planner: **8/8**;
- strict symbol correlation: **9/9**;
- preflight: **6/6**;
- fail-closed executor: **9/9**;
- shared project/fleet reporting: **6/6**;
- public registry remains the same eight providers.

A real symbol scan is still not claimed. Current live blockers remain:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

UPM did not install govulncheck, download a database, or change telemetry settings.

## Remaining promotion gate

Do not add a public symbol route until all remaining items are satisfied atomically:

1. run the executor against a real local `file://` DB after preflight passes;
2. verify project-state mutation and characterize actual non-project cache/tool side effects;
3. prove strict correlation against real govulncheck output and existing UPM OSV occurrences;
4. define a conservative source/build-state fingerprint and separate symbol persistence/freshness semantics;
5. keep ordinary status free of hidden symbol analysis.

The shared project/fleet model is groundwork only; it is not a public presentation route.
