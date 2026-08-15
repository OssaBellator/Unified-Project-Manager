# Current review notes

These notes capture the current review boundary for `feature/initial-control-plane`. They are intentionally stricter than a feature checklist: anything listed as lower-level or follow-up should not be inferred as public capability.

## Public native providers

The public native-provider surface currently consists of:

- Go;
- npm;
- pnpm;
- Yarn Berry 2+;
- Cargo;
- uv.

Public graph/why/impact/fleet/SBOM/advisory behavior for those providers is documented in `NATIVE_PROVIDERS.md`.

Yarn Classic is not covered by the Berry provider.

## Yarn Berry review boundary

The Berry provider uses exact descriptor/locator resolution identity and preserves workspace/virtual package structure. Project install-state persistence is redirected to a temporary path, network is disabled inside Berry, and cache mutation is blocked.

SBOM/advisory identity is additionally scoped to locators reachable from active workspace/project roots. A stored Yarn package record that is not reachable from a workspace root is not promoted into CycloneDX/SPDX or advisory scan inventory merely because `yarn info --all --recursive` returned it.

### Narrow compatibility cleanup still open

`yarn_graph.py` currently also sets a hardened-mode environment override. That setting is not required for the provider's safety contract and may be a compatibility liability for older Berry runtimes if the setting name is not recognized there.

Preferred cleanup:

1. remove the hardened-mode override;
2. retain Berry network refusal, temporary install state, telemetry suppression, and immutable cache;
3. let a runtime that cannot reconstruct the graph under those offline constraints fail explicitly;
4. update the focused Yarn execution test and `NATIVE_PROVIDERS.md` wording at the same time.

This is a compatibility cleanup, not a reason to relax the offline fail-closed policy.

## Structured Poetry/PDM provider: implemented below the public line

A structured TOML provider exists for `poetry.lock` and `pdm.lock`, with focused local regressions, but it is intentionally not included in public provider coverage yet.

Implemented lower-level semantics include:

- static package/relationship ingestion with no subprocess/network/mutation;
- exact-one-candidate resolution only;
- explicit duplicate-name ambiguity;
- project-root dependency paths;
- marker/optional-aware conditional reachability;
- reachable ambiguity reporting without fake paths;
- registry-only PyPI PURL identity;
- reachable-only SBOM inventory;
- omission of conditional/ambiguous edges from unconditional SBOM relationships;
- contract validation that rejects unsupported dependency shapes or record-level package conditions.

Promotion remains gated on routing graph, why, impact, fleet impact, SBOM, audit, and provider status together. Until then, `provider_registry` should not claim Poetry/PDM native relationship coverage.

See `PYTHON_LOCK_PROVIDERS.md`.

## Exact advisory evidence contract

Project and fleet advisory flows now share the same evidence rule:

- provider-backed inventory is constructed once for an applied native scan;
- the exact CycloneDX document given to OSV-Scanner is retained on the result;
- persisted evidence fingerprints that exact document;
- native inventory is not rebuilt after scanning;
- successful scanner output without the exact scanned BOM is an evidence failure rather than a silent success;
- fleet output distinguishes planning, native-inventory, scanner, and evidence failures;
- ordinary status never reruns scanner/providers to manufacture freshness.

## Local validation boundary

No GitHub Actions workflow is part of this project.

The latest aggregate local driver is:

```sh
sh ./scripts/check-all-local-latest.sh
```

Focused provider drivers include:

```sh
sh ./scripts/test-yarn-native.sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-python-lock-native-validated.sh
```

The current execution environment cannot materialize the entire private feature branch as a local checkout, so the latest full branch has not been executed end-to-end here. Keep review/test claims conservative until the branch is run from a normal local clone.

## Merge hygiene

The branch contains many small commits because repository writes were performed through GitHub's contents API during this implementation session. If/when the user authorizes merge, a squash merge is the appropriate default to avoid importing that implementation transport history into `main`.

Do not merge this PR without explicit user authorization.
