# Go symbol reachability

This document describes a **pre-public** provider boundary for Go vulnerable-symbol reachability. It is not routed through `upm audit`, provider status, or any other public command yet.

## Evidence ladder

`go mod why -m` can establish package-import reachability, but not that a vulnerable function is called. Govulncheck source mode supplies the stronger static call-graph layer.

```text
dependency graph < package import graph < vulnerable symbol/call graph
```

Even symbol/call-graph evidence is not runtime/data-flow reachability or exploitability.

## Current implementation state

The branch now contains these **pre-public** layers:

- govulncheck v1 streaming-JSON parser;
- module/package/symbol finding classification;
- local-database offline plan builder;
- read-only telemetry/executable/local-state preflight;
- strict correlation to existing UPM Go advisory impacts;
- a fail-closed subprocess executor gated by that exact preflight;
- a public-boundary regression keeping govulncheck out of the provider registry;
- focused local tests and an aggregate local driver.

There is still **no public CLI flag or provider route**.

## JSON evidence contract

UPM accepts only the govulncheck protocol/evidence mode it explicitly models:

```text
protocol_version = v1.0.0
scan_mode = source
scan_level = symbol
db = file://...
```

All four values are mandatory. The first stream message must contain only `config`. Subsequent protocol messages may arrive in any valid order.

Govulncheck can emit module-, package-, and symbol-level findings for one vulnerability. Only a finding whose first trace frame contains a function/method is treated as vulnerable-symbol/call-graph evidence.

## Strict advisory correlation

`correlate_govulncheck_symbols(...)` requires all of these to agree:

1. UPM impact provider is `go-modules` for the exact component;
2. UPM advisory ID is the finding's GO OSV ID or an alias carried by that exact govulncheck OSV record;
3. govulncheck vulnerable-frame module equals the UPM impact's **effective module** identity;
4. exact module version is present and equal on both sides.

Anything weaker remains unmatched with a refusal reason. Alias overlap never bypasses module/version identity. Missing versions fail closed. Multiple competing UPM aliases for one finding are treated as ambiguous.

Duplicate exact UPM impacts consolidate dependency paths rather than multiplying symbol claims.

### Replacement identity

Govulncheck vulnerability analysis reports replacement module path/version, so symbol correlation uses UPM `evidence.effective_name`.

This deliberately differs from `go mod why -m`, whose package-import query uses the logical/original module namespace:

```text
import query target = logical required module
symbol correlation module = effective replacement module
```

## Offline plan boundary

Planned command:

```text
govulncheck -format json -mode source -scan symbol -db file:///... ./...
```

Environment guards:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

These prevent module-proxy fallback, ambient workspace inheritance, checksum-database network lookup, and automatic toolchain download. Because `GOSUMDB=off`, symbol evidence does **not** claim fresh dependency checksum verification.

## Read-only preflight

`preflight_govulncheck_symbol(...)` never launches govulncheck. It revalidates:

- project directory;
- local vulnerability DB;
- Go executable;
- planned govulncheck executable;
- `go env GOTELEMETRY == off`.

It does not change telemetry configuration. A stale/missing project or DB, missing executable, failed telemetry query, or any telemetry mode other than `off` makes preflight not ready.

## Fail-closed executor

`execute_govulncheck_symbol(...)` is implemented but remains pre-public.

Execution is allowed only when the exact preflight belongs to the exact plan project and database and reports ready. A mismatched/stale preflight cannot authorize another plan.

The executor:

- replaces only argv[0] with the preflight-resolved govulncheck executable;
- invokes directly with `shell=False` semantics through `subprocess.run`;
- uses the plan's offline/single-module environment guards;
- does not retry online or alter telemetry settings;
- treats any nonzero return code as execution failure;
- parses output only after exit code 0;
- rejects malformed/unsupported JSON evidence;
- verifies the stream's reported database URI exactly matches the planned local `file://` DB.

### JSON-mode exit semantics

Govulncheck's documented JSON mode returns exit code 0 whether vulnerabilities are found or not. Therefore UPM never treats a zero exit as a clean result by itself.

```text
returncode == 0 -> command completed; inspect validated JSON findings
returncode != 0 -> execution failure; do not treat stdout as valid symbol evidence
```

A successful execution with symbol findings and a successful execution with zero symbol findings are both valid command executions. Vulnerability presence comes from the parsed report, not process status.

## Mutation and side-effect boundary

The executor contract is intentionally conservative:

```text
project mutation = none planned; real-runtime verification still required
non-project cache/tool mutation = possible
reclaimability inference = none
persisted = false
```

A mocked subprocess contract is not enough to prove real govulncheck project-state immutability or cache behavior. Those remain runtime validation requirements.

## Reachability interpretation

A symbol-level finding means govulncheck static analysis found a call path to a vulnerable symbol under the scan's source/build configuration.

It does not prove production execution, attacker-controlled data flow, complete modeling of reflection/unsafe/dynamic behavior, or exploitability.

Pre-public symbol output therefore retains:

```text
runtime_reachability = not-evaluated
exploitability = not-established
persisted = false
```

## Public boundary

Govulncheck remains absent from the eight-provider public relationship registry. No `--go-symbol-reachability` flag exists. Ordinary status does not execute this parser, preflight, executor, or correlation path.

## Validation

Dedicated local driver:

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

It covers parser/planner, strict correlation, public-boundary, preflight, and executor regressions.

Focused reconstructed/local evidence in this constrained runtime:

- parser/planner contract: **8/8**;
- strict dependency-impact/symbol correlation: **9/9**;
- read-only preflight: **6/6**;
- fail-closed executor contract: **9/9**;
- public registry remains the same eight relationship providers.

A real symbol scan is still not claimed. Current live blockers remain:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

UPM did not install govulncheck, download a database, or change telemetry settings.

The full private branch still has not been materialized and run end-to-end here.

## Remaining promotion gate

Do not add a public symbol-reachability route until all remaining items are satisfied atomically:

1. run the executor against a real local `file://` vulnerability DB after preflight passes;
2. verify project-state mutation and characterize actual non-project cache/tool side effects;
3. bind strict correlation to real govulncheck output and existing UPM OSV-Scanner occurrences without weakening exact module/version rules;
4. share one project/fleet presentation model;
5. define symbol-evidence persistence/freshness semantics separately from existing OSV evidence;
6. keep ordinary status free of hidden symbol analysis.

The executor is still groundwork, not partial public promotion.
