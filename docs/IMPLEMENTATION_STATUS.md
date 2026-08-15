# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation/integration pass. It distinguishes routed public behavior from deliberately unsupported areas rather than listing already-integrated work as future work.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- Go, package.json/pnpm, Cargo, and uv workspace ownership models;
- structural/deep health, policy, integrity snapshots, native verification, and evidence-aware status;
- preview-first package-manager delegation, repair, initialization, tasks, exec, workspace sync, and cache maintenance;
- mutation receipts plus receipt history/drift and optional local receipt-chain anchoring;
- project/fleet status, policy, inventory, duplicate, impact, storage, and advisory views;
- machine-wide cache/store measurement;
- public read-only Go/Cargo physical cache provenance for explicitly registered projects;
- CycloneDX 1.7 and SPDX 2.3 export with deterministic mixed-project application topology;
- preview-first OSV-Scanner advisory scanning with exact scanned-SBOM evidence retention;
- opt-in Go package-import advisory reachability kept separate from dependency/runtime/exploitability claims;
- relationship-provider coverage surfaced in local status without hidden provider execution.

No GitHub Actions workflows are used. Validation remains local and script-driven. The aggregate entrypoint is:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused slices include:

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
```

## Native relationship providers

`--native` relationship analysis has eight public provider families: Go, npm, pnpm, Yarn Berry 2+, Cargo, uv, Poetry, and PDM. Provider-specific graph/scope evidence remains visible rather than being flattened into one universal resolver model.

Go component-scoped relationship execution is cache-only/offline and workspace-isolated through both `GOPROXY=off` and `GOWORK=off`. Poetry/PDM share the certainty-aware `structured-lock-dependency-graph` model and fail closed on unsupported structured-lock semantics.

## Fleet native inventory and duplicate correlation

`projects inventory --native` and `projects duplicates --native` route all eight public provider families while retaining provider-specific occurrence meaning. Duplicate grouping remains observation-only with `reclaimable=false`.

## SBOM interoperability and project topology

CycloneDX 1.7 and SPDX 2.3 are public formats. Registry PURLs are emitted only where provenance supports them, and provider-specific uncertainty is retained rather than flattened.

Aggregate SBOMs represent mixed-project topology explicitly with deterministic aggregate/component application anchors. Provider merges preserve those anchors and generic normalized inventory does not manufacture component→package dependency edges. Topology-only anchors are excluded from advisory package counts.

See `SBOM_PROJECT_COMPONENTS.md`.

## Advisory and reachability model

Advisory scanning is explicit because OSV scanning may use network access. Implemented public layers include preview-first project/fleet plans, provider-backed `audit --native`, exact scanned CycloneDX retention/fingerprinting, dependency-path correlation across all eight public provider families, structured-lock uncertainty evidence, and local evidence/policy states.

### Go package-import reachability

A stronger source/import layer is public for Go as an explicit audit enrichment:

```sh
upm audit . --native --go-import-reachability
upm audit . --native --go-import-reachability --apply
upm projects audit --native --go-import-reachability
upm projects audit --native --go-import-reachability --apply
```

The flag requires full `--native` inventory. It uses component-scoped `go mod why -m` with `GOPROXY=off` and `GOWORK=off` only for vulnerable Go impacts already correlated to the retained native scan inventory.

Evidence remains deliberately narrower than runtime exploitability:

```text
build_constraints = any-tags
current_build_configuration_reachability = not-evaluated
test_imports_may_contribute = true
api_reachability = not-evaluated
runtime_reachability = not-evaluated
exploitability = not-established
persisted = false
```

Go replacements preserve logical import-query identity separately from effective replacement advisory identity. The command is project-state read-only: Go's loader suppresses automatic `go.mod`/`go.sum` writes for `why`, and a real local Go 1.23.2 regression confirmed both files stayed byte-for-byte unchanged.

See `REACHABILITY_EVIDENCE.md`.

### Pre-public Go symbol/call-graph groundwork

A lower-level govulncheck contract exists, but **symbol reachability is not a public UPM capability yet**. There is still no public CLI route/provider advertisement.

Implemented groundwork now includes:

- strict govulncheck v1 streaming-JSON parsing;
- mandatory explicit `scan_mode=source`, `scan_level=symbol`, and local `file://` database evidence;
- module/package/symbol finding separation;
- an offline plan with `GOPROXY=off`, `GOWORK=off`, `GOSUMDB=off`, and `GOTOOLCHAIN=local`;
- strict symbol correlation to existing UPM Go advisory impacts requiring exact component, advisory identity/alias, effective module, and exact version;
- replacement-aware correlation against the effective replacement module identity;
- fail-closed read-only preflight that revalidates project/DB/executables and requires `go env GOTELEMETRY` already be `off`;
- an explicit public-boundary regression keeping govulncheck out of the eight-provider public registry.

Alias overlap alone cannot attach symbol evidence. Missing/mismatched module/version identity remains unmatched with a reason. Multiple competing UPM advisory aliases for one finding are refused as ambiguous.

The preflight never launches govulncheck and never changes telemetry settings. The live environment currently remains not ready: Go is installed, telemetry is `local`, govulncheck is absent, and no candidate local vulnerability DB was found. None of those conditions were mutated automatically.

There is intentionally no real govulncheck execution claim yet. Public promotion remains gated on a real local-DB execution test, project/cache side-effect characterization, binding the strict correlation core to real output, shared project/fleet presentation, and separate persistence/freshness semantics.

Because the offline plan disables the checksum database, symbol evidence must not be described as fresh dependency-integrity verification.

See `GO_SYMBOL_REACHABILITY.md`.

### Reachability classes still not public

UPM does **not** currently provide a public provider for vulnerable API/symbol reachability as a routed command, runtime/data-flow reachability, or exploitability determination. The pre-public govulncheck groundwork does not change that public boundary.

Ordinary status/policy evaluation does not perform hidden scans, dependency-provider execution, source/import queries, or symbol analysis.

## Cache/storage safety and provenance

`upm cache provenance` is public for Go and Cargo only. Go attribution uses native-reported module directories plus selected-version download artifacts derived from the already-escaped physical path. Cargo attribution uses canonical registry/git source objects, including one-object multi-crate git checkout grouping.

Safety fields remain invariant:

```text
unattributed_means_unused = false
reclaimable_bytes = null
reclaimable = false
```

npm, pnpm, and uv cache/store internals remain without per-package physical attribution rather than being heuristically reverse-engineered.

See `CACHE_PROVENANCE.md`.

## Current validation state

The runtime available to this implementation session cannot materialize the entire private branch as a local checkout, so full-suite claims remain conservative. The repository contains layered local validation scripts rather than GitHub Actions.

Focused reconstructed/local validation completed for:

- Poetry/PDM reachability hardening: **5/5**;
- all-provider fleet core: **4/4**;
- mixed-project SBOM anchors: **5/5**;
- initial cache physical mapping: **5/5** plus additional Cargo physical-object precision checks;
- cache provenance report semantics: **7/7** plus separate identity-precision checks;
- Go package-import reachability core: **7/7**;
- Go relationship environment isolation: **3/3**;
- real local Go 1.23.2 `go mod why -m` project-state immutability: **1/1**;
- pre-public govulncheck parser/planner contract: **8/8**;
- strict govulncheck-to-UPM symbol correlation: **9/9**;
- read-only govulncheck executable/local-state/telemetry preflight: **6/6**;
- live symbol preflight blockers independently confirmed without changing tool, DB, or telemetry state.

Project/fleet Go import-reachability CLI regressions and the pre-public symbol driver are committed and included in aggregate local validation, but the full private checkout has not been executed end-to-end in this runtime.

## Important remaining gaps

The next highest-value work is now:

1. implement and validate a fail-closed pre-public govulncheck executor, then prove it against a real local vulnerability DB before public promotion;
2. characterize project-state and non-project cache/tool side effects of that real execution;
3. define shared project/fleet symbol output plus separate persistence/freshness semantics before any public CLI route;
4. add runtime/data-flow or exploitability evidence only where an ecosystem-native contract can support it;
5. deepen physical cache provenance only where manager-native identity supports it;
6. validate more of the very large branch in one materialized checkout when private branch bytes are available;
7. eventually add SPDX 3.x as a dedicated model, not a shallow 2.3 translation.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, workspaces, security scanners, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
