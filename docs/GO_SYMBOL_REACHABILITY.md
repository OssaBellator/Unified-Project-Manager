# Go symbol reachability

This document describes a **pre-public** provider boundary for Go vulnerable-symbol reachability. It is not routed through `upm audit`, provider status, or any other public command yet.

## Why this is separate from import reachability

`go mod why -m` can establish that some package from a module is present in Go's package import graph. It cannot establish that a vulnerable function or method is called.

Go's official `govulncheck` source mode supplies a stronger semantic layer: static call-graph analysis can emit symbol-level findings with call traces.

UPM therefore keeps these evidence classes separate:

```text
dependency graph < package import graph < vulnerable symbol/call graph
```

Even symbol/call-graph evidence is still not runtime/data-flow reachability or exploitability.

## Current implementation state

The branch currently contains pre-public groundwork only:

- a govulncheck v1 streaming-JSON parser;
- explicit module/package/symbol finding classification;
- OSV alias retention;
- an offline local-database plan builder;
- read-only telemetry/executable/local-state preflight;
- strict correlation from symbol findings to existing UPM Go advisory impacts;
- an explicit regression keeping govulncheck out of the public provider registry;
- focused local tests and a dedicated local driver.

There is **no govulncheck subprocess executor and no public CLI flag** yet.

## JSON evidence contract

UPM accepts only the govulncheck protocol and evidence mode it has explicitly modeled:

```text
protocol_version = v1.0.0
scan_mode = source
scan_level = symbol
db = file://...
```

All four values are mandatory. Missing source/symbol mode values are not treated as implied defaults because the evidence class depends on them.

The first JSON message must contain only `config`. Subsequent protocol messages may arrive in any valid order.

Govulncheck may emit several findings for one vulnerability while analysis progresses:

- module-level finding — first frame has module identity only;
- package-level finding — first frame has package identity but no function;
- symbol-level finding — first frame has a function/method.

Only the third class is treated as vulnerable-symbol/call-graph evidence. UPM does not flatten module/package findings into a called-symbol claim.

## Strict advisory correlation

Govulncheck findings reference a Go OSV ID; the corresponding OSV message may include CVE/GHSA aliases. UPM retains those aliases, but alias overlap alone is never enough to attach symbol evidence to an existing advisory occurrence.

`correlate_govulncheck_symbols(...)` requires all of the following:

1. the UPM dependency impact is a `go-modules` impact for the exact component being analyzed;
2. its advisory ID is either the finding's GO OSV ID or an alias carried by that exact govulncheck OSV record;
3. the govulncheck vulnerable frame's module equals the UPM impact's **effective module** identity;
4. the module version matches exactly and is present on both sides.

If any condition fails, the finding stays in `unmatched` with an explicit reason. Missing versions fail closed. If multiple different UPM advisory aliases would claim one symbol finding, correlation is refused as ambiguous.

Multiple otherwise-identical UPM dependency-impact rows consolidate their dependency paths into one symbol match instead of duplicating the symbol claim.

### Go replacement identity

Go vulnerability analysis uses replacement module path/version for vulnerability lookup/reporting. UPM therefore correlates a govulncheck frame against `evidence.effective_name`, not the logical required module path.

This is intentionally different from `go mod why -m`, whose import query uses the logical/original module namespace. For a replacement, UPM may therefore retain:

```text
import query target = logical required module
symbol correlation module = effective replacement module
```

without pretending those identities are interchangeable.

The symbol frame's package import path is retained as reported and is not used as a substitute for module/version identity.

## Offline plan boundary

The pre-public plan requires a caller-supplied local vulnerability database directory and converts it to a `file://` URI.

Planned command shape:

```text
govulncheck -format json -mode source -scan symbol -db file:///... ./...
```

The plan sets:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

These guards prevent module-proxy fallback, ambient workspace inheritance, checksum-database network lookup, and automatic Go toolchain download.

Because `GOSUMDB=off`, this symbol provider does **not** claim fresh dependency checksum verification. Integrity evidence remains separate.

## Read-only preflight boundary

`preflight_govulncheck_symbol(...)` does not launch govulncheck. It revalidates:

- project directory still exists;
- local vulnerability database still exists;
- `go` is resolvable;
- the planned govulncheck executable is resolvable;
- `go env GOTELEMETRY` succeeds and reports exactly `off`.

The telemetry query runs under the same no-network/single-module environment guards as the plan. Preflight never changes telemetry configuration.

Its result explicitly says:

```text
executes_govulncheck = false
mutates_telemetry_configuration = false
project_mutation = none
network = none
```

If telemetry is `local`, `on`, missing, or cannot be inspected, preflight is not ready. UPM will not run a settings-changing command merely to satisfy the provider.

## Mutation and side-effect boundary

The future symbol analysis is intended to avoid project manifest/source mutation. UPM does **not** claim that a govulncheck subprocess would be globally side-effect free.

Source analysis may use or update non-project Go/tool caches and local analysis state. Therefore the eventual execution contract must remain:

```text
project mutation = none planned
non-project cache/tool mutation = possible
reclaimability inference = none
```

A real executor test is still required before promotion.

## Reachability interpretation

A symbol-level govulncheck finding means static analysis found a call path to a vulnerable symbol under the scan's source/build configuration.

It does not prove that the path executes in production, that attacker-controlled data reaches the operation, that all dynamic/reflection/unsafe behavior is modeled, or that the vulnerability is exploitable.

Pre-public matched rows therefore retain:

```text
runtime_reachability = not-evaluated
exploitability = not-established
persisted = false
```

## Validation

Dedicated local driver:

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

It currently includes parser/planner, strict correlation, public-boundary, and preflight regressions.

Focused reconstructed/local evidence in this constrained runtime:

- parser/planner contract: **8/8** checks passed;
- strict dependency-impact/symbol correlation: **9/9** checks passed;
- read-only telemetry/executable/local-state preflight: **6/6** checks passed;
- public registry remains the same eight relationship providers; govulncheck is not advertised.

A real symbol scan is not claimed. In this environment:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

UPM did not install govulncheck, download a database, or change telemetry settings.

The full private branch still has not been materialized and run end-to-end here.

## Remaining promotion gate

Do not add a public `--go-symbol-reachability` flag until all remaining items are satisfied atomically:

1. execute govulncheck against a real local `file://` vulnerability DB after the existing preflight passes;
2. verify project-state mutation and characterize actual non-project cache/tool side effects during that execution;
3. bind the already-strict correlation core to real govulncheck output and existing UPM OSV-Scanner occurrences without weakening module/version requirements;
4. share one project/fleet output model;
5. define separate persistence/freshness semantics for symbol evidence;
6. keep ordinary status free of hidden symbol analysis.

The existing parser, correlation, and preflight code are groundwork for that gate, not a partial public promotion.
