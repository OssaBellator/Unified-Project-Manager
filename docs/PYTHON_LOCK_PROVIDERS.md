# Structured Poetry and PDM lock-provider contract

Poetry and PDM are public native relationship providers on `feature/initial-control-plane`.

- Poetry provider id: `poetry-lock`;
- PDM provider id: `pdm-lock`;
- shared relationship scope: `structured-lock-dependency-graph`.

They are routed through public native graph, why, project/fleet impact, CycloneDX/SPDX, advisory inventory/path correlation, and provider-status coverage. The implementation remains deliberately conservative: unsupported lock semantics fail closed instead of falling back to environment-dependent manager commands or a guessed resolver.

## Why static lock evidence

UPM does not need to invoke `poetry show` or `pdm list` merely to recover relationships already present in structured TOML lock state.

The providers read:

- `poetry.lock` for components owned by Poetry;
- `pdm.lock` for components owned by PDM.

They use Python's standard-library `tomllib`. No subprocess, environment activation, network access, package installation, or project mutation occurs.

Native manifests and lockfiles remain authoritative. These providers normalize lock evidence; they are not replacement resolvers.

## Provider boundary

`python_lock_provider.py` centralizes provider naming, scope, ownership, validated execution, and generic-static-inventory suppression.

The general Python adapter records lock packages as broad static observations. Native Poetry/PDM inventory must not merge certainty-aware provider results on top of those observations because doing so could reintroduce orphan packages or flatten ambiguity. Public native SBOM/advisory routing therefore suppresses provider-owned generic lock observations before merging the validated structured-lock result.

Provider registry capabilities are:

- `execution = false`;
- `network = none`;
- `mutation = none`;
- graph/why/impact/SBOM relationship support enabled.

## Identity

A locked package occurrence retains:

- normalized package name for matching;
- original name;
- locked version;
- source kind;
- lock groups where available;
- a distinct internal package id.

Source kinds remain provenance-sensitive. Registry-backed packages may become PyPI PURLs. Git, path/directory, URL/file, editable, and other non-registry records are not relabeled as registry packages.

## Relationship resolution

Lock dependency records are parsed differently by manager but normalized to one edge model:

- Poetry `[package.dependencies]` records retain version text, markers, optionality, and multi-constraint records;
- PDM dependency strings retain the package name, requirement text, and PEP-508 marker text.

UPM does **not** run a second resolver over those requirements.

A dependency resolves to an internal target only when the lock contains exactly one candidate with the normalized name. Multiple candidates remain explicit ambiguity:

- `target_id = null`;
- all candidate package ids are retained;
- `ambiguous = true`;
- public why/impact/audit paths do not select a candidate by version guessing.

A dependency with zero candidates is retained as unresolved, which is distinct from ambiguity.

## Project roots and direct conditions

Each provider creates a synthetic project root and connects normalized direct manifest dependencies using the same exact-one-candidate rule.

Direct conditions are preserved before graph construction:

- PEP 621 optional dependency groups become optional root edges;
- Poetry `{ optional = true }` dependencies become optional root edges;
- optional Poetry dependency groups become optional root edges;
- Poetry direct `markers`, `python`, and `platform` constraints remain attached;
- multiple Poetry direct constraint records remain separate normalized edges rather than being flattened.

This prevents optional or environment-qualified direct declarations from becoming unconditional graph reachability.

## Resolved, conditional, and possible reachability

Marker-bearing and optional edges are graph evidence, not unconditional reachability.

`python_lock_reachability.py` retains, per path:

- exact project/package path;
- accumulated marker expressions;
- optional-edge count;
- ambiguity-hop count;
- certainty: `unconditional`, `conditional`, or `possible`.

A package can have both unconditional and conditional resolved paths. Resolved paths and possible paths are returned separately so ambiguity is never relabeled as ordinary conditional resolution.

When a reachable edge has multiple candidate package ids, UPM records the unresolved hop as `?dependency-name` and then conservatively traverses **every** candidate branch as possible reachability. That possible state propagates through descendants of each candidate. For example:

```text
project:.:python -> parent@1.0.0 -> ?shared -> shared@1.0.0 -> leaf@3.0.0
```

means `leaf@3.0.0` is scan-relevant only because one unresolved `shared` candidate could lead to it. It does **not** mean UPM selected `shared@1.0.0` for a concrete Python environment.

The ambiguity record itself retains the path ending at `?shared`, candidate ids, marker/optional conditions, and truncation state. The corresponding `possible_packages` records retain candidate/descendant paths beyond that hop.

This alignment is important: native SBOM already propagates possible inventory through ambiguous candidate subgraphs, so public why/impact/advisory evidence must be able to explain every package intentionally admitted to the scan.

### Path budgets and multiplicity

Traversal is path-sensitive. Distinct parent chains are retained even when they have the same marker/optional state; the provider no longer collapses two valid dependency paths merely because their conditions match.

To keep pathological graphs bounded, reachability has explicit defaults:

- `max_paths_per_package = 64`;
- `max_search_states = 10000`.

A path-list cap sets `paths_truncated = true`. Reaching the traversal-state budget sets `search_truncated = true` and marks returned package/ambiguity path sets as truncated. UPM surfaces truncation in JSON and text output instead of returning an apparently complete partial explanation.

`python_lock_queries.py` is the command-neutral public query contract used by `why`, project `impact`, fleet impact, and advisory correlation. It reports:

- resolved `packages` and retained paths;
- separate `possible_packages` reached through ambiguity;
- unconditional versus conditional resolved match counts;
- ambiguity records and candidate ids;
- search/path truncation evidence;
- whether the answer is uncertain;
- the explicit interpretation that dependency reachability is not source/API/runtime reachability or exploitability.

`python_lock_render.py` is the shared text renderer for project why, project impact, and fleet impact. This prevents possible-only queries from degrading into an empty provider heading and keeps marker/optional/truncation text aligned with the JSON contract.

## Public graph behavior

`graph --native` exposes Poetry/PDM as static providers. Preview contains no manager command and reports the certainty policy as `conditional-and-ambiguity-preserving`.

Executed graph output includes:

- structured package identities and source kinds;
- resolved edges;
- optional/marker conditions;
- explicit ambiguous candidate sets;
- explicit unresolved references.

Unsupported lock shapes or record-level conditions fail the provider instead of being silently dropped.

## SBOM behavior

CycloneDX/SPDX inventory starts from project-root reachability, not every lock record.

Only reachable registry-backed packages receive PyPI PURLs. Inventory has three useful states:

- **unconditional** — at least one unconditional resolved project path exists;
- **conditional** — only marker/optional-qualified resolved paths exist;
- **possible** — reachability traversed one or more ambiguous references.

Possible state propagates through dependencies of every ambiguous candidate. This is deliberately conservative for vulnerability inventory: if any candidate branch can lead to a registry package, that package can remain scan-visible without being presented as a definitely selected dependency.

Relationship admission is stricter than package admission:

- uniquely resolved + unconditional registry-to-registry edge: may become a dependency relationship;
- marker-bearing or optional edge: package identities may be present, but the edge is omitted;
- ambiguous edge: candidates/descendants may remain possible inventory, but no fabricated selected edge is emitted;
- unresolved edge: omitted and distinguished from ambiguity;
- non-registry endpoint: omitted rather than relabeled as PyPI.

CycloneDX records provider uncertainty through reachability properties and counts for conditional, ambiguous, unresolved, and non-registry edges omitted from unconditional relationships. SPDX 2.3 keeps the conservative package subset and omits relationships that are not unconditional.

Public SPDX routing constructs the base document after `suppress_python_lock_static_inventory(...)`, preventing broad structured-lock seed records from leaking back into the certainty-aware document.

## Advisory inventory and path correlation

Public `audit --native` and `projects audit --native` use the same validated structured-lock results that produced the exact CycloneDX document given to OSV-Scanner.

`NativeCycloneDxInventory` retains Poetry/PDM results alongside the BOM. Advisory correlation therefore does not rebuild a second graph after scanning.

For a resolved vulnerable package, advisory evidence retains:

- provider/component/package identity;
- all dependency paths;
- marker/optional conditions per path;
- whether an unconditional path exists;
- path/search truncation state.

For a vulnerable package reachable only through ambiguity—whether it is the direct candidate or a transitive descendant—advisory evidence reports `possible-via-ambiguous-lock-reference` and retains the full candidate path including each `?dependency` hop. This is possible dependency reachability, not proof that a candidate is installed for a specific environment or that vulnerable code is exploitable.

Provider failure remains fail-closed: a malformed/unsupported structured lock prevents native advisory inventory rather than falling back to broad static package observations.

## Provider status

`provider_registry` advertises `poetry-lock` and `pdm-lock` for components with the corresponding authoritative lockfile. Project/fleet status uses that registry without executing provider parsing or advisory scans merely to display coverage.

A configured provider can still fail when explicitly executed if the lock contains semantics UPM intentionally does not model. Coverage means a provider is configured for that manager/state, not that arbitrary future lock syntax will be guessed successfully.

## Local validation

Run the comprehensive structured-lock slice:

```sh
sh ./scripts/test-python-lock-native-validated.sh
```

The dedicated public promotion regression is:

```sh
sh ./scripts/test-python-lock-public-provider.sh
```

Focused checks also remain available:

```sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
```

The validated slice also includes `test_python_lock_render.py` and the path-multiplicity regression.

The repository regressions cover provider ids/scope/coverage, supported lock-contract validation, Poetry and PDM relationship parsing, direct optional/marker/multi-constraint conditions, distinct path multiplicity, explicit path/search budgets, conditional and ambiguity evidence, transitive possible branches, reachable-only CycloneDX/SPDX, possible scan inventory, exact-BOM advisory evidence reuse, text rendering, and public graph/why/impact/SBOM/advisory routing.

In the constrained implementation runtime, the current reconstructed reachability rewrite passed **5/5** focused tests covering resolved conditional paths, direct ambiguity, transitive possible reachability, distinct same-condition path multiplicity, path caps, and search-state truncation. A separate reconstructed query/advisory check confirmed that a transitive package below an ambiguous candidate is reported as `possible-via-ambiguous-lock-reference` with its full `?dependency` path. The shared text-renderer smoke check also passed.

The full private branch still cannot be materialized here, so the committed end-to-end shell drivers are for a normal local clone and are not misrepresented as having run in this environment.

Validation is local-only; no GitHub Actions workflow is required or used.
