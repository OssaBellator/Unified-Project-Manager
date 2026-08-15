# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. Anything described as follow-up should not be inferred as implemented public capability.

## Public native providers

The public native-provider surface currently consists of:

- Go;
- npm;
- pnpm;
- Yarn Berry 2+;
- Cargo;
- uv;
- Poetry;
- PDM.

Public graph/why/impact/fleet/SBOM/advisory behavior is documented in `NATIVE_PROVIDERS.md`. Poetry/PDM's conservative structured-lock contract is detailed in `PYTHON_LOCK_PROVIDERS.md`.

Yarn Classic remains outside the Berry provider.

## Yarn Berry review boundary

The Berry provider uses exact descriptor/locator resolution identity and preserves workspace/virtual package structure. Project install-state persistence is redirected to a temporary path, network is disabled inside Berry, and cache mutation is blocked.

SBOM/advisory identity is scoped to locators reachable from active workspace/project roots. A stored Yarn package record that is not reachable from a workspace root is not promoted merely because `yarn info --all --recursive` returned it.

The provider does not force `YARN_ENABLE_HARDENED_MODE`. Execution and preview share `yarn_execution_policy.py`, and preview correctly reports hardened mode as `unchanged`. Required fail-closed controls remain network refusal, temporary install state, telemetry suppression, and immutable cache behavior.

Focused regressions:

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
```

Both are included in `scripts/test-yarn-native.sh`.

## Poetry/PDM public promotion

The structured TOML providers for `poetry.lock` and `pdm.lock` are public as `poetry-lock` and `pdm-lock`, sharing `structured-lock-dependency-graph` scope.

Promotion is routed across the public surface rather than represented by provider-status metadata alone:

- `graph --native` exposes static validated structured-lock packages, resolved/unresolved/ambiguous edges, and marker/optional conditions;
- `why --native`, project `impact --native`, and fleet impact serialize the same command-neutral certainty-aware query object;
- native CycloneDX/SPDX suppress broad Python adapter lock observations before merging certainty-aware reachable registry identities;
- native project/fleet audit retains the same validated Poetry/PDM graph results alongside the exact CycloneDX document scanned by OSV-Scanner;
- `provider_registry` reports Poetry/PDM coverage with `execution=false`, `network=none`, and `mutation=none`.

### Reachability hardening completed during promotion review

A deeper consistency pass found that the SBOM layer already propagated `possible` inventory through dependencies of every ambiguous candidate, while public why/impact/advisory reachability stopped at the first ambiguous hop. That could admit a transitive package to the OSV scan without retaining a dependency explanation for it.

The shared reachability model now:

- keeps resolved `packages` separate from ambiguity-derived `possible_packages`;
- renders each unresolved ambiguity hop as `?dependency` before branching into every candidate;
- propagates possible reachability through descendants of each candidate rather than only exposing direct candidates;
- retains marker/optional conditions and ambiguity-hop count on every path;
- keeps the direct ambiguity record with candidate IDs and the path ending at `?dependency`;
- lets advisory correlation explain transitive possible findings with the same full path that justified their scan inventory.

For example, `project -> parent -> ?shared -> shared@1 -> leaf` means `leaf` is possible via one unresolved branch; it does not mean UPM selected `shared@1` for a concrete environment.

The same review exposed a pre-existing path-multiplicity test contract that the implementation had not satisfied. Reachability is now path-sensitive and bounded:

- distinct same-condition parent paths are retained instead of being collapsed by a node/condition visited set;
- `max_paths_per_package` defaults to 64;
- `max_search_states` defaults to 10000;
- returned package/ambiguity objects carry `paths_truncated` when necessary;
- the query result carries `search_truncated` if the traversal budget is reached.

`python_lock_render.py` is shared by project why, project impact, and fleet impact text output so possible-only queries, ambiguity paths, conditions, and truncation warnings are visible outside JSON too.

Unsupported lock dependency shapes or package-record-level conditions remain explicit provider failures. Public support does not imply UPM will guess arbitrary future Poetry/PDM lock semantics.

A serializer bug found during reconstructed local validation was also fixed: `PythonLockPath.to_dict()` returns JSON-ready lists for path nodes and markers rather than relying on `json.dumps` to convert tuples implicitly.

## Exact advisory evidence contract

Project and fleet advisory flows share the same rule:

- provider-backed inventory is constructed once for an applied native scan;
- the exact CycloneDX document given to OSV-Scanner is retained on the result;
- persisted evidence fingerprints that exact document;
- native inventory is not rebuilt after scanning;
- successful scanner output without the exact scanned BOM is an evidence failure;
- fleet output distinguishes planning, native-inventory, scanner, and evidence failures;
- ordinary status never reruns scanner/providers merely to manufacture freshness.

Poetry/PDM participate in this same retained-evidence path through `NativeCycloneDxInventory.python_lock_results`. Resolved findings retain conditional path evidence; direct or transitive ambiguity-derived findings are labeled `possible-via-ambiguous-lock-reference` and retain the full `?dependency` candidate path.

## Local validation boundary

No GitHub Actions workflow is part of this project.

The latest aggregate local driver is:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused provider drivers include:

```sh
sh ./scripts/test-yarn-execution-policy.sh
sh ./scripts/test-yarn-execution-compat.sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-python-lock-provider-boundary.sh
sh ./scripts/test-python-lock-direct-conditions.sh
sh ./scripts/test-python-lock-query-contract.sh
sh ./scripts/test-python-lock-sbom-uncertainty.sh
sh ./scripts/test-python-lock-native-inventory.sh
sh ./scripts/test-python-lock-public-provider.sh
sh ./scripts/test-python-lock-native-validated.sh
```

`test-python-lock-native-validated.sh` now also includes the path-multiplicity and shared text-renderer regressions.

Focused reconstructed/local validation in this execution environment includes the previously recorded Yarn and structured-lock slices plus the current reachability hardening:

- the current reachability rewrite passed **5/5 reconstructed tests** covering conditional paths, direct ambiguity, transitive possible branches, same-condition path multiplicity/path caps, and search-state truncation;
- a separate reconstructed query/advisory check confirmed that a transitive package below an ambiguous candidate is reported as `possible-via-ambiguous-lock-reference` with the full `?dependency` path;
- the shared possible-path text-renderer smoke check passed.

The end-to-end public-provider shell driver is committed and included in `test-python-lock-native-validated.sh`, which is included by `check-all-local-latest.sh`. This execution environment still cannot materialize the entire private branch as one checkout, so that full driver and the full aggregate have not been claimed as executed here.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during implementation. If/when merge is authorized, a squash merge remains the appropriate default to avoid importing transport history into `main`.

Do not merge this PR without explicit user authorization.
