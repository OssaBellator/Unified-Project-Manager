# Govulncheck scan-SBOM review boundary

This note records the latest **pre-public** Go symbol-analysis trust-chain tightening. It does not add a public provider or CLI route.

## Required native scan inventory

Accepted govulncheck source/symbol evidence must now contain exactly one native `SBOM` protocol message in addition to the leading config message.

UPM retains:

- SBOM Go version where reported;
- module build-list path/version pairs;
- root package paths.

The source-symbol parser refuses missing, duplicate, malformed, or rootless SBOM evidence. This means a successful process exit is still insufficient for accepted symbol evidence if the scanner-declared inventory is absent or invalid.

## Correlation chain

Strict symbol correlation now requires the vulnerable symbol frame's module/version to exist in the govulncheck SBOM build list **before** it can attach to a UPM Go advisory impact.

The full correlation chain is:

```text
validated protocol + source/symbol/local-DB config
  -> scanner-declared scan SBOM
  -> vulnerable frame module/version present in SBOM build list
  -> GO OSV id or alias from that exact govulncheck OSV record
  -> exact UPM component + go-modules provider
  -> UPM effective module identity
  -> exact UPM version
```

Missing scanner SBOM, build-list contradiction, advisory mismatch, module mismatch, missing version, version mismatch, or competing advisory identities all fail closed.

## Scan declaration identity

UPM also has a deterministic pre-public SHA-256 identity over scanner-declared config/SBOM provenance:

- protocol and scanner identity;
- local DB URI and reported modification time;
- config/SBOM Go versions;
- normalized module build list;
- normalized roots.

This is intentionally labeled:

```text
scope = govulncheck-scan-declaration
freshness = not-established
source_state_fingerprint = false
build_configuration_fingerprint = false
```

It can associate reports with the exact scanner-declared module/root inventory. It must not be treated as proof that source files, build configuration, call graph, runtime behavior, or exploitability are unchanged.

## Validation

Focused local-checkout drivers:

```sh
sh ./scripts/test-go-symbol-sbom-contract.sh
sh ./scripts/test-go-symbol-scan-declaration.sh
```

Focused reconstructed checks completed in the constrained implementation runtime:

- scan-SBOM parser/correlation/executor invariants: **12/12**;
- scan-declaration identity invariants: **5/5**.

The full private branch is still not represented as having run end-to-end in this runtime.

## Public boundary

Govulncheck remains outside the eight public relationship providers. There is no public symbol-reachability CLI route and no persisted symbol freshness state.
