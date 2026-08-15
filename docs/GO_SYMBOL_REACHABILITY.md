# Go symbol reachability

This document describes a **pre-public** provider boundary for Go vulnerable-symbol reachability. It is not routed through `upm audit`, provider status, or any other public command yet.

## Why this is separate from import reachability

`go mod why -m` can establish that some package from a module is present in Go's package import graph. It cannot establish that a vulnerable function or method is called.

Go's official `govulncheck` tool provides the stronger semantic layer UPM needs: source mode can perform static call-graph analysis and emit symbol-level findings with call traces.

UPM therefore treats these as distinct evidence classes:

```text
dependency graph < package import graph < vulnerable symbol/call graph
```

Even symbol/call-graph evidence is still not runtime/data-flow reachability or exploitability.

## Current implementation state

The branch currently contains only:

- a govulncheck v1 streaming-JSON parser;
- explicit module/package/symbol finding classification;
- OSV alias retention for future cross-scanner correlation;
- an offline local-database plan builder;
- telemetry-mode fail-closed validation;
- focused local tests and a dedicated local driver.

There is **no subprocess executor and no public CLI flag** for this provider yet.

That is deliberate. Public promotion is blocked until the execution/preflight boundary is proven end-to-end and correlation with UPM's existing OSV-Scanner evidence is exact enough to avoid mismatching advisories.

## JSON evidence contract

UPM accepts only the current govulncheck protocol it has explicitly modeled:

```text
protocol_version = v1.0.0
scan_mode = source
scan_level = symbol
db = file://...
```

All four values are mandatory for this provider. Missing mode/level values are not treated as implied defaults because the evidence class depends on them.

The first JSON message must contain only `config`. Subsequent streaming messages may appear in any order, matching the govulncheck protocol's documented ordering guarantees.

Govulncheck may emit several findings for one vulnerability while analysis progresses:

- module-level finding — first frame has module identity only;
- package-level finding — first frame has package identity but no function;
- symbol-level finding — first frame has a function/method.

Only the third class is treated as vulnerable-symbol/call-graph evidence. UPM does not flatten module/package findings into a called-symbol claim.

For methods, UPM retains receiver + function separately and exposes the combined symbol for rendering.

## OSV identity and aliases

Govulncheck emits Go vulnerability OSV records and findings that reference the Go OSV ID. The OSV record may also contain aliases such as CVE or GHSA IDs.

UPM retains:

```text
GO-... -> aliases[]
```

This is groundwork only. A future public integration must prove correlation between the exact govulncheck finding and the exact advisory occurrence already reported by UPM's OSV-Scanner flow. Alias overlap alone must not manufacture a package/version match.

## Offline plan boundary

The pre-public plan requires a local vulnerability database directory and converts it to a `file://` URI passed explicitly with `-db`.

Planned command shape:

```text
govulncheck -format json -mode source -scan symbol -db file:///... ./...
```

The plan also sets:

```text
GOPROXY = off
GOWORK = off
GOSUMDB = off
GOTOOLCHAIN = local
```

These guards mean:

- no module-proxy fallback;
- no ambient parent `go.work` inheritance;
- no checksum-database network lookup;
- no automatic Go toolchain download.

Because `GOSUMDB=off`, this symbol provider does **not** claim to freshly verify dependency checksums. Source-integrity verification remains a separate evidence concern.

## Telemetry boundary

Govulncheck participates in Go telemetry. Users may configure telemetry mode as `local`, `on`, or `off`.

A future executor is allowed to run only when telemetry mode is already:

```text
off
```

UPM will not change the user's telemetry configuration automatically merely to enable this provider.

This is stricter than the default Go telemetry behavior because the provider's intended execution contract is no network and no hidden telemetry upload.

## Mutation boundary

The planned symbol analysis is intended to avoid project manifest/source mutation. However, UPM does **not** claim that a future govulncheck subprocess is globally side-effect free.

Source analysis may use or update non-project Go/tool caches and local analysis state. Therefore the provider contract is:

```text
project mutation = none planned
non-project cache/tool mutation = possible
reclaimability inference = none
```

A public executor must preserve this distinction in preview/output rather than describing the operation as universally read-only.

## Reachability interpretation

A symbol-level govulncheck finding means static analysis found a call path to a vulnerable symbol under the scan's source/build configuration.

It does not prove:

- that the call path executes in production;
- that attacker-controlled data reaches the vulnerable operation;
- that reflection/unsafe/dynamic behavior is fully modeled;
- that the vulnerability is exploitable in the deployed system.

Govulncheck itself documents conservative handling of function pointers/interfaces and limitations around reflection/unsafe analysis. UPM must preserve those limitations instead of upgrading a static call trace into an exploitability verdict.

## Validation

Dedicated local driver:

```sh
sh ./scripts/test-go-symbol-reachability.sh
```

The reconstructed constrained-runtime slice currently passes **8/8** checks covering:

- module/package/symbol finding separation;
- symbol/receiver rendering;
- OSV alias retention independent of message order;
- protocol-version refusal;
- missing/wrong source-mode or symbol-level refusal;
- remote/non-file database refusal;
- ambiguous JSON-message refusal;
- local-DB plan guards and telemetry fail-closed behavior.

The full private branch still has not been materialized and run end-to-end in this execution environment.

## Promotion gate

Do not add a public `--go-symbol-reachability` flag until all of these are true atomically:

1. telemetry preflight is implemented without mutating user telemetry settings;
2. the subprocess execution boundary is locally tested with a real govulncheck runtime and local file DB;
3. project-state mutation is checked explicitly;
4. cache/tool side effects are represented honestly;
5. govulncheck OSV/package/version/symbol findings are correlated to existing UPM advisory occurrences without alias-only guessing;
6. project and fleet output share one correlation model;
7. persistence/freshness semantics are defined separately from existing OSV scan evidence;
8. ordinary status remains free of hidden symbol analysis.
