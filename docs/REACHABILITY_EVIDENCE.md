# Reachability evidence

UPM treats dependency presence, dependency-graph reachability, source/import reachability, API/symbol reachability, runtime reachability, and exploitability as different evidence classes.

A stronger-sounding class must never be inferred from a weaker one.

## Evidence ladder

### 1. Inventory presence

A concrete package/module identity is represented in the selected static or native inventory.

This says only that the package is part of the inventory scope. It does not establish that a project dependency path reaches it.

### 2. Dependency-graph reachability

Native or structured-lock relationship evidence connects a project/component root to the dependency occurrence.

Examples include npm logical lock-tree paths, Cargo package-ID edges, uv/Poetry/PDM lock reachability, and Go module requirement paths.

This remains **dependency reachability**. It does not establish a source import, API call, runtime call, vulnerable data flow, or exploitability.

### 3. Package-import reachability

A language/tool-native package import graph connects project code (or tests included in that graph) to a package supplied by the dependency.

The initial public implementation is Go-only and opt-in during native advisory scanning:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

After an applied native scan reports a vulnerable Go module already correlated to UPM's retained native dependency inventory, UPM may execute:

```text
go mod why -m <module>
```

through the existing `GOPROXY=off` wrapper.

Go defines `go mod why -m` as a query over the **package import graph**, finding a path to any package in the target module rather than querying the module requirement graph.

#### Build-constraint scope

The current Go command implementation loads the `why` package graph with `imports.AnyTags()`. UPM therefore records:

```text
build_constraints = any-tags
current_build_configuration_reachability = not-evaluated
```

A positive package-import result is intentionally broader than “reachable in this exact production build.” UPM does not relabel it as current-build reachability.

The default package graph can also include test imports, so UPM records:

```text
test_imports_may_contribute = true
```

These fields are emitted for both positive and negative successful queries because they describe the query semantics, not the answer.

States are explicit:

- `package-import-reachable` — the query succeeded and returned an import path in Go's any-build-tag package graph;
- `not-package-import-reachable` — the query succeeded and Go reported that the main module does not need a package in that module under the same any-build-tag package graph;
- `query-failed` — the import query could not be completed. This is not converted into a negative reachability result.

Each row also retains the already-known dependency path for context, but the dependency path and import path remain separate fields.

### 4. API/symbol reachability

Not implemented as a public evidence provider.

Package-import reachability does not prove that a vulnerable function, method, type, symbol, or API is referenced.

Current Go import evidence reports:

```text
api_reachability = not-evaluated
```

### 5. Runtime/data-flow reachability

Not implemented as a public evidence provider.

Static import or symbol evidence would still not prove that a runtime execution path reaches the vulnerable operation with relevant inputs.

Current Go import evidence reports:

```text
runtime_reachability = not-evaluated
```

### 6. Exploitability

UPM does not infer exploitability from package inventory, dependency paths, imports, or advisory presence.

Current reachability rows report:

```text
exploitability = not-established
```

A future exploitability claim would need a separate evidence contract appropriate to the advisory class and runtime context.

## Audit execution boundary

`--go-import-reachability` requires `--native`.

That requirement ensures UPM only runs the stronger import query for Go advisory impacts already correlated to the retained native inventory used by the scan. Compatibility-only `--native-go` does not currently retain the same correlation object and therefore is not accepted for this enrichment.

Preview remains non-executing. The Go import query runs only after an applied native scan, and only for vulnerable Go module impacts. Multiple advisories for the same component/module share one import query.

The query uses UPM's offline Go wrapper (`GOPROXY=off`). It is an explicit audit enrichment, not something ordinary `status` or policy evaluation runs silently.

## Persistence boundary

The exact OSV-scanned CycloneDX document and scanner evidence keep their existing persisted evidence contract.

Go package-import reachability is currently **report-only**:

```text
persisted = false
```

It is not written into `.upm/audits/osv.json`, and ordinary status does not replay or surface it as durable evidence.

This avoids mixing two freshness models: the persisted OSV evidence is bound to an exact scanned SBOM, while package-import reachability depends on the source/package graph present when the explicit query runs.

A future persisted source-reachability format would need its own source-state fingerprint and freshness contract.

## Failure semantics

Source/import enrichment never changes a valid scanner result into a false clean/vulnerable result.

If `go mod why -m` cannot complete, the row is `query-failed` with its error/return code. The independently valid OSV evidence may still be persisted because scanner validity and source-reachability enrichment are separate evidence layers.

Likewise, a successful `not-package-import-reachable` result is not a statement that an advisory is impossible to exploit through all build configurations, generated code, reflection, plugins, runtime loading, or future source changes. It is only the result of Go's any-build-tag package-import graph queried at that moment.
