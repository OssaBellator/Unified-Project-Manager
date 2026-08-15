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
6. deterministic local vulnerability-DB and versioned-module runtime fixtures;
7. deterministic filesystem snapshot/delta support for runtime side-effect characterization;
8. fail-closed positioned finding-frame/source correspondence against the Go-native observed package/syntax-file set;
9. an optional real govulncheck end-to-end regression plus explicit characterization command, both gated by existing tool/telemetry state;
10. a public-boundary regression keeping govulncheck out of the eight-provider registry.

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

## Positioned finding-frame/source correspondence

For a govulncheck frame that reports `Position.Filename`, UPM can now perform a narrower fail-closed correspondence check against the candidate Go-native source observation. Exact observed package identity and effective module/version must agree, and the module-relative scanner filename must resolve to one observed `CompiledGoFiles`/`syntax_go_files` entry for that package.

Scanner paths with absolute roots or `..` traversal are refused. `/` and `\\` separators are normalized. Absolute compiled-file entries are accepted only when they remain inside the observed package directory; generated/cache absolute paths outside that directory are not reinterpreted as ordinary module-relative source files. Replacement packages use effective module identity for scanner agreement while deriving their package-relative path deliberately from the logical/effective module namespaces. Standard-library frames and ambiguous package/file candidates remain conservative failures.

Even a match remains only frame/source correspondence:

```text
source_selection_equivalence = not-established
build_configuration_equivalence = not-established
freshness = not-established
runtime_reachability = not-evaluated
exploitability = not-established
public = false
persisted = false
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

The executor remains pre-public/report-only. A committed characterization harness can now report project/local-fixture/isolated-cache deltas around a real scanner run, but the actual side-effect result remains unproven until that command runs with real prerequisites.

## Shared project/fleet reporting

`build_go_symbol_project_report(...)` consumes an already-completed execution plus existing dependency impacts. It never launches govulncheck.

- valid successful execution -> strict correlation is produced;
- successful execution with a symbol that cannot be correlated -> unmatched symbol remains explicit;
- blocked/failed/invalid execution -> `correlation = null`; UPM does **not** manufacture an empty/negative symbol-reachability result.

Fleet aggregation only combines already-built reports and keeps independent counts for execution failures, raw symbol findings, correlated matches, and unmatched symbol findings.

Both project and fleet representations remain:

```text
public = false
persisted = false
runtime_reachability = not-evaluated
exploitability = not-established
```

## Deterministic local validation fixtures

The real-runtime regression does not require a downloaded public vulnerability database or a network-fetched dependency.

### Synthetic Go vulnerability DB

`tests/support_go_vulndb_fixture.py` writes only the published v1 filesystem endpoints consumed by the Go vulnerability client:

```text
index/db.json
index/modules.json
index/vulns.json
ID/GO-2099-0001.json
```

The synthetic record affects `example.com/dep` from version `0` until fixed `1.2.4`, specifically package `example.com/dep/pkg` symbol `Danger`, with alias `CVE-2099-0001`.

The fixture does not import `x/vulndb/internal` packages or depend on the vulnerability team's internal report/YAML format.

### Versioned dependency through a local module proxy

A filesystem replacement is intentionally not used for the real symbol fixture: local replacements have no replacement version, which is unsuitable for exact vulnerability-version correlation.

`tests/support_go_symbol_runtime_fixture.py` instead generates a Go module proxy for:

```text
example.com/dep@v1.2.3
```

using the standard proxy endpoints:

```text
@v/list
@v/v1.2.3.info
@v/v1.2.3.mod
@v/v1.2.3.zip
```

The zip uses the required `example.com/dep@v1.2.3/` prefix. A tiny app requires that version with no `replace` and calls `pkg.Danger`.

Fixture setup runs `go mod download` only against the generated `file://` proxy with an isolated `GOMODCACHE`/`GOCACHE` and `GOSUMDB=off`. After the versioned module is cached, the actual analysis environment switches to `GOPROXY=off`.

A real local Go 1.23.2 check already proves this transition works: the dependency is populated from the local file proxy and subsequently resolves with `GOPROXY=off`.

Local fixture preparation helper:

```sh
sh ./scripts/prepare-go-symbol-validation-fixture.sh /tmp/upm-go-symbol-fixture
```

This does not install govulncheck or change telemetry.

## Optional real-runtime regression

`tests/test_go_symbol_real_runtime.py` is included in the local symbol driver but skips unless all of these already hold:

- `go` exists;
- `govulncheck` exists;
- `go env GOTELEMETRY` is exactly `off`.

The test never installs the tool and never changes telemetry.

When runnable, it:

1. generates the local DB, proxy, app, and isolated caches;
2. populates only the isolated module cache from the file proxy;
3. snapshots every project file after setup;
4. runs UPM preflight + executor with the synthetic DB and `GOPROXY=off`;
5. requires the synthetic symbol finding and strict UPM correlation;
6. builds the shared project report;
7. requires the full project snapshot to remain byte-for-byte identical.

That test is committed but **has not run here** because the current prerequisites do not allow it.

For the promotion gate, `scripts/characterize-go-symbol-runtime.ps1` (or the `.sh` equivalent) is stricter than a skipped unittest: unavailable prerequisites return exit `2` with `status = blocked`. When runnable it snapshots the project, generated proxy/DB, isolated module cache, and isolated build cache after fixture preparation; records source-observation and govulncheck deltas separately; checks real scanner declaration alignment; requires exactly one expected synthetic `Danger` symbol finding; requires that positioned vulnerable frame to correspond to the observed dependency package/syntax file; and requires strict UPM correlation exactly once. It fails on project/proxy/DB mutation. Effects outside those observed roots remain `not-observed`, so a successful run still does not prove arbitrary machine-wide non-mutation.

## Persistence/freshness boundary

Persistence is intentionally **not implemented yet**.

A safe symbol-evidence freshness contract cannot be based only on `go.mod`/`go.sum` or the OSV-scanned SBOM. Govulncheck source analysis depends on the actual build/source configuration; local replacements and source files outside a simplistic manifest fingerprint can change call-graph results.

Ordinary status therefore remains free of hidden symbol analysis and has no symbol freshness state to replay.

## Side-effect and interpretation boundary

```text
project mutation = none planned; real-runtime verification still required
observed-root side-effect characterization = harness committed; real result pending
non-project cache/tool mutation = possible; effects outside isolated observed roots remain unobserved
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
- deterministic vulnerability-DB fixture: **7/7**;
- fully local versioned runtime fixture: **5/5**, including real Go file-proxy -> offline-cache resolution;
- positioned finding-frame/source correspondence: **11/11**;
- deterministic side-effect snapshot/delta helpers: **4/4**;
- public registry remains the same eight providers.

A real govulncheck symbol scan is still not claimed. The deterministic DB/source fixtures now exist, so current live blockers are narrower:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
```

UPM did not install govulncheck or change telemetry settings.

## Remaining promotion gate

Do not add a public symbol route until all remaining items are satisfied atomically:

1. run the optional real-runtime regression after govulncheck is already installed and telemetry is already `off`;
2. run the committed characterization command and review its exact isolated-cache deltas without treating unobserved machine state as clean;
3. prove scanner declaration alignment, positioned finding-frame/source correspondence, and strict correlation against the real govulncheck stream generated from the deterministic fixture without claiming complete source-selection equivalence;
4. define a conservative source/build-state fingerprint and separate symbol persistence/freshness semantics;
5. keep ordinary status free of hidden symbol analysis.

The fixtures remove external DB/dependency-network requirements; they do not replace the need for a real govulncheck runtime validation.
