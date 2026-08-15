# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Anything described as follow-up should not be inferred as implemented public capability.

## Public boundary

The public native-provider surface remains exactly Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Govulncheck is **not** a public provider and has no public CLI route.

Public Go package-import reachability remains report-only, component-scoped, offline (`GOPROXY=off`), ambient-workspace-isolated (`GOWORK=off`), replacement-aware, and explicitly weaker than symbol/runtime/exploitability evidence.

## Pre-public Go vulnerable-symbol stack

Five lower layers now exist without public promotion:

1. **Parser/planner** — strict govulncheck v1 source/symbol/local-DB semantics.
2. **Correlation** — exact component + advisory ID/alias + effective module + exact version; mismatch/ambiguity stays unmatched.
3. **Preflight** — local inspection only; exact project/DB, executables, and telemetry `off`; no settings mutation.
4. **Executor** — only launches after exact-plan ready preflight; no shell; offline environment; nonzero is failure; zero is parsed/validated JSON; planned DB and reported DB must match exactly.
5. **Public-boundary regression** — govulncheck remains absent from the eight-provider registry and public Go metadata retains both isolation guards.

### JSON exit-code boundary

Govulncheck JSON mode returns success even when vulnerabilities are detected. The executor therefore never equates exit code 0 with “clean.”

```text
0      = command completed; inspect validated JSON findings
nonzero = execution failure; do not accept stdout as valid symbol evidence
```

The mocked executor regressions cover both zero-with-symbol-findings and zero-with-no-findings as valid command executions.

### Preflight binding

A preflight result authorizes only the exact project and local DB it inspected. Passing a ready preflight for another project or DB blocks execution before launch.

### Correlation refusal rules

Alias overlap alone never creates symbol attachment. Wrong provider/component, effective-module mismatch, missing version, exact-version mismatch, or multiple competing UPM advisory identities all fail closed. Replacement correlation uses the effective replacement module identity; import-query identity remains the logical/original module namespace.

### Side-effect boundary

The executor remains pre-public and does **not** claim real-runtime project immutability yet. Current output says:

```text
project mutation = none planned; real-runtime verification still required
non-project cache/tool mutation = possible
persisted = false
runtime reachability = not evaluated
exploitability = not established
```

`GOSUMDB=off` is part of the no-network plan, so symbol evidence is not fresh checksum/integrity verification.

### Live blocker

No real govulncheck scan is claimed in this environment:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

No tool install, DB download, or telemetry mutation was performed to bypass those conditions.

## Remaining promotion gate

Do not add public symbol routing until all remaining pieces are proven atomically:

- real local-DB govulncheck execution after preflight;
- project-state and non-project cache/tool side-effect characterization;
- strict correlation against real output;
- shared project/fleet presentation;
- separate symbol persistence/freshness semantics;
- ordinary status remaining free of hidden symbol analysis.

## Validation boundary

No GitHub Actions workflow is part of this project. Aggregate local entrypoint:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused reconstructed/local results include:

- Poetry/PDM reachability: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- cache physical mapping: **5/5** plus additional precision checks;
- cache report semantics: **7/7** plus identity checks;
- Go package-import reachability: **7/7**;
- Go relationship environment isolation: **3/3**;
- real local Go import-query immutability: **1/1**;
- govulncheck parser/planner: **8/8**;
- strict symbol correlation: **9/9**;
- govulncheck preflight: **6/6**;
- fail-closed govulncheck executor: **9/9**.

The full private checkout still cannot be materialized and run end-to-end here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API. If/when merge is authorized, squash merge remains the appropriate default.

Do not merge this PR without explicit user authorization.
