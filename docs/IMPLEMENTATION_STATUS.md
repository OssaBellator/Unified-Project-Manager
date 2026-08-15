# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes mixed Node/Python/Rust/Go discovery, workspace-aware operations, receipts, health/policy/status, native relationship analysis, all-provider fleet inventory/duplicates, CycloneDX 1.7 and SPDX 2.3, preview-first OSV scanning, Go/Cargo physical cache provenance, and opt-in Go package-import advisory reachability.

No GitHub Actions workflows are used. Validation remains local and script-driven through:

```sh
sh ./scripts/check-all-local-latest.sh
```

The public relationship-provider surface remains exactly eight families: Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM.

## Public Go package-import reachability

`--go-import-reachability` remains the only public stronger-than-dependency Go enrichment. It requires full native scan inventory, uses component-scoped `go mod why -m` with `GOPROXY=off` and `GOWORK=off`, retains any-build-tag/test-import caveats, handles replacements without collapsing logical/effective identity, remains report-only, and does not claim current-build/API/runtime/exploitability reachability.

A real local Go 1.23.2 regression confirms the query leaves `go.mod` and `go.sum` byte-for-byte unchanged.

See `REACHABILITY_EVIDENCE.md`.

## Pre-public Go symbol/call-graph groundwork

Vulnerable-symbol reachability is **not public**, but the lower-level govulncheck stack now includes five layers:

1. **Parser/planner** — exact protocol `v1.0.0`, explicit source/symbol mode, local `file://` DB, module/package/symbol separation, offline plan guards.
2. **Strict correlation** — exact component + govulncheck OSV/alias + effective module + exact version; mismatch or ambiguity fails closed.
3. **Read-only preflight** — revalidates project, DB, Go/govulncheck executables, and telemetry; requires telemetry already `off` and never changes it.
4. **Fail-closed executor** — launches only after exact-plan preflight, uses the resolved executable/no shell, rejects nonzero exits, malformed JSON, or DB mismatch, and treats vulnerability presence as parsed evidence rather than process status.
5. **Public-boundary regression** — govulncheck stays out of the eight-provider public registry and public Go relationship metadata retains `GOPROXY=off` + `GOWORK=off`.

### Executor semantics

The executor uses govulncheck JSON mode. In that mode exit code 0 means the command completed, regardless of whether vulnerabilities were found. A nonzero return code is an execution failure. Clean/vulnerable symbol state comes only from the validated streaming report.

The executor is still pre-public and report-only. Its output explicitly retains:

```text
public = false
persisted = false
runtime_reachability = not-evaluated
exploitability = not-established
project mutation = none planned; real-runtime verification still required
non-project cache/tool mutation = possible
```

A preflight object can authorize execution only for the exact project and DB it inspected.

### Remaining real-runtime gate

No real govulncheck scan is claimed. Current live environment blockers remain:

```text
govulncheck executable = absent
Go executable = /usr/local/go/bin/go
GOTELEMETRY = local
usable local vulnerability DB = not found
```

UPM did not install a tool, download a DB, or change telemetry to bypass those blockers.

Before public promotion, the executor still must be exercised against a real local DB; project-state and non-project cache/tool side effects must be characterized; strict correlation must be proven against real govulncheck output; project/fleet presentation and separate persistence/freshness semantics must be defined; ordinary status must remain free of hidden analysis.

Because the offline plan sets `GOSUMDB=off`, symbol analysis is not fresh dependency-integrity verification.

See `GO_SYMBOL_REACHABILITY.md`.

## Cache/storage safety

Public Go/Cargo cache provenance remains observation-only. It never converts unattributed bytes into unused/reclaimable bytes. npm/pnpm/uv opaque cache internals remain unsupported rather than heuristically reverse-engineered.

## Current validation state

The runtime still cannot materialize the entire private branch, so full-suite claims remain conservative. Focused reconstructed/local validation includes:

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
- fail-closed govulncheck executor contract: **9/9**.

The full private checkout has not been run end-to-end here.

## Important remaining gaps

1. validate the pre-public govulncheck executor against a real local vulnerability DB and characterize actual side effects;
2. define shared project/fleet symbol presentation and symbol-evidence persistence/freshness before any public route;
3. add runtime/data-flow or exploitability evidence only where ecosystem-native evidence supports it;
4. deepen physical cache provenance only where manager-native identity supports it;
5. validate the very large branch in one materialized private checkout when available;
6. eventually implement SPDX 3.x as a dedicated model.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
