# Implementation status

This document records the current `feature/initial-control-plane` branch after the extended implementation pass. It distinguishes public CLI surfaces from lower-level primitives that are implemented/tested but not yet promoted into the main command surface.

## Public control-plane foundation

Current public behavior includes:

- Node, Python, Rust, and Go project discovery;
- first-class Go workspace discovery/inspection and guarded workspace synchronization;
- structural `doctor` health plus opt-in installed-state checks;
- toolchain and Node package-manager version checks;
- SHA-256 project-state snapshots;
- preview-first package-manager delegation and repair;
- preview-first project task DAGs plus supported native tasks;
- manager-scoped argv-only native execution;
- project/fleet status, policy, inventory, duplicate, impact, and storage views;
- machine-wide cache/store measurement;
- cache integrity/maintenance operations with explicit mutation classes;
- CycloneDX 1.7 export;
- preview-first OSV-Scanner advisory scanning for one project or the explicit project registry.

No GitHub Actions workflows are used. Validation remains local and script-driven through:

```sh
sh ./scripts/check.sh
```

## Native relationship providers

`--native` relationship analysis now has three public providers:

- **Go** — selected modules, module requirement graph, package-import `why`, replacements, module provenance;
- **npm** — lock-only logical dependency tree through npm itself, including duplicate logical occurrences;
- **Cargo** — `cargo metadata --locked --offline`, preserving package IDs, dependency kinds/targets, and workspace ownership.

Public `graph`, `why`, `impact`, fleet impact, and native CycloneDX enrichment retain provider/scope labels rather than pretending these evidence classes are identical.

## Go workspace model

Go workspaces are first-class rather than ambient process state.

- `go.work` / `go.work.sum` are discovered and snapshot-tracked;
- workspace inspection delegates to `go work edit -json`;
- explicit workspace graph/impact uses the selected workspace;
- normal component-scoped Go commands disable ambient workspace inheritance;
- `go work sync` is preview-first and records before/after hashes;
- external workspace members require explicit opt-in.

A separate offline-run helper has been implemented/tested to force `GOPROXY=off` for native Go relationship queries. Public provider wiring is being tightened around that helper so “read-only project files” is never confused with “zero network.”

## Advisory model

Advisory scanning is explicit because it may use network access.

Implemented layers include:

- preview-first project and fleet OSV-Scanner plans;
- temporary CycloneDX scan artifacts;
- correct distinction between OSV exit code 1 (findings) and scanner failure;
- dependency-path correlation for npm/Cargo/Go and conservative uv relationship evidence;
- versioned persisted advisory evidence at `.upm/audits/osv.json`;
- evidence fingerprints bound to the exact scanned SBOM;
- local evidence states: absent, current-clean, current-vulnerable, stale, native-inventory-unverified, invalid;
- policy fields for requiring current advisory evidence, maximum evidence age, and known-vulnerability budgets;
- a library primitive that persists only valid scanner outcomes (clean or vulnerable), never scanner failures.

Ordinary policy evaluation uses persisted local evidence and does not perform a hidden advisory scan.

## Cache/storage safety

The cache subsystem intentionally separates:

- `storage` — measurement only;
- `check` — non-mutating integrity checks where available;
- `verify` — verification that may perform manager maintenance;
- `prune` — manager-defined removal of unused/unreferenced data;
- `clean` — explicit full-cache removal.

Implemented explicit maintenance plans include pnpm store prune, uv cache prune, npm full cache clean, and separate Go build/module cache clean operations.

Storage measurements are never converted into generic deletion targets.

## Implemented/tested lower-level providers awaiting final public integration

### uv universal lock relationships

A static `uv.lock` relationship provider is implemented without subprocess/network access.

It preserves:

- package name/version/source identity;
- project-member/local source classification;
- dependency markers;
- candidate package IDs for forked/ambiguous references;
- only uniquely identified relationship edges;
- reverse impact paths over unambiguous edges.

The provider deliberately refuses to pick the first package when a universal-lock dependency could refer to multiple locked versions.

### SPDX 2.3

A real SPDX 2.3 JSON exporter is implemented/tested with:

- SPDX document identity/creation metadata;
- required package assertions;
- Package URL external references where provenance supports them;
- document `DESCRIBES` relationships;
- provider-backed package `DEPENDS_ON` relationships;
- deterministic content-derived document namespace when creation time is fixed.

SPDX 3.x is not claimed through a version-string translation; it requires a dedicated object-model implementation.

### package.json workspaces

A package.json workspace inspector is implemented/tested for npm/Yarn/Bun-style declarations:

- workspace glob expansion;
- member package identity;
- root/member manager mismatch;
- duplicate workspace package names;
- unmatched workspace patterns;
- nested package.json files outside the declared workspace.

`pnpm-workspace.yaml` is intentionally not hand-parsed with a fragile YAML subset; pnpm-specific workspace modeling should remain native-tool-backed.

## Important remaining gaps

The next highest-value integration work is:

1. finish cache-only/offline-by-default Go graph wiring across all public providers;
2. promote the conservative uv graph into public graph/why/impact/SBOM/fleet routes;
3. promote persisted advisory evidence into the public status output and add an explicit scan-and-save CLI option;
4. expose SPDX through the main SBOM command;
5. model package.json/pnpm workspaces in the common workspace model so `install --all` can collapse workspace-owned operations instead of planning redundant member installs;
6. add relationship providers for Poetry/PDM and other native ecosystems only where lock semantics can be represented without guessing;
7. add cache ownership/provenance evidence before attempting any automated reclaim recommendation;
8. keep source/API/runtime reachability separate from dependency-graph impact.

## Safety boundary

Native manifests, resolvers, package managers, toolchains, and cache semantics remain authoritative. UPM may normalize observations and orchestrate native commands, but it should refuse ambiguity rather than replace ecosystem-specific truth with a universal guess.
