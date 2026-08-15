# Provider-backed advisory scanning

`upm audit` keeps dependency inventory and vulnerability lookup as separate trust boundaries.

## Static mode

Without a native-inventory flag, UPM scans the concrete resolved inventory already available from its normal project model.

Persisted evidence from this mode can be rechecked locally against the same deterministic static CycloneDX fingerprint and classified as current-clean/current-vulnerable/stale.

## `--native-go`

`--native-go` remains as a compatibility subset. During `--apply`, Go selected-module inventory is built with `GOPROXY=off` before OSV-Scanner is invoked.

The inventory stage is cache-only/offline. The OSV scanner stage may use network access.

## `--native`

`--native` builds the temporary scan SBOM from every configured authoritative provider whose inventory contract is local/offline:

- Go selected modules/relationships with `GOPROXY=off`;
- npm native CycloneDX from `package-lock` via `npm sbom --package-lock-only`;
- pnpm native CycloneDX from `pnpm-lock.yaml` via `pnpm sbom --lockfile-only`;
- Cargo metadata through `--locked --offline`;
- static universal `uv.lock` evidence.

Unsupported components may still contribute trustworthy static resolved inventory already present in UPM's normal model.

An explicitly requested provider failure is not silently replaced by a weaker online or heuristic source.

## Preview privacy

Preview does not execute provider inventory and does not run OSV-Scanner.

It reports the intended inventory mode and scanner command template only. This keeps `audit --native` preview free of both package-manager subprocesses and network-capable scanner execution.

## Apply sequence

On `--apply`:

1. discover current project/component/workspace state;
2. build provider-backed CycloneDX using only local/offline provider contracts;
3. write that BOM to a short-lived temporary `.cdx.json` file;
4. invoke the exact resolved `osv-scanner` binary;
5. classify scanner exit `0` as clean and `1` as findings;
6. delete the temporary BOM when execution returns;
7. persist valid clean/vulnerable evidence bound to the exact scanned BOM hash.

Scanner failures are never persisted as clean evidence.

## Local status after native scanning

Ordinary `status` does not silently re-execute native providers merely to claim the evidence is current.

Persisted `native-go` / `native-providers` evidence is therefore reported as native-inventory-unverified by the zero-network local status evaluator until a future explicit verification mechanism can reproduce the same provider fingerprint under the same contract.

This is deliberate: a stored result from authoritative native inventory is useful evidence, but local status should not invent freshness by comparing it to a weaker static inventory.

## Dependency-path correlation

Advisory identity and dependency-path evidence remain separate.

Current relationship providers can correlate findings with:

- npm logical paths;
- pnpm workspace/logical paths, including alias/scope/dedupe evidence;
- Cargo locked/offline workspace paths;
- Go module-requirement paths;
- conservative uv universal-lock paths.

These paths establish dependency-graph reachability only. They do not establish source import, call reachability, runtime exploitability, or effective configuration exposure.
