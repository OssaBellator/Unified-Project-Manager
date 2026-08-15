# Govulncheck scan declaration identity

This is a **pre-public provenance primitive**, not a source/build freshness model.

Govulncheck source-symbol JSON includes a native SBOM message describing the scan's Go version, module build list, and root packages. UPM now retains that message and requires it for accepted pre-public source-symbol evidence.

## Identity contents

`govulncheck_scan_declaration_identity(...)` canonicalizes and hashes only scanner-declared evidence:

- govulncheck protocol version;
- scanner name/version where reported;
- local vulnerability DB URI and reported DB modification time;
- Go version from config;
- Go version from the native scan SBOM;
- SBOM module build-list path/version pairs;
- SBOM root packages.

The result exposes a deterministic SHA-256 plus the normalized declaration.

Module and root ordering do not affect the identity. Changing scanner version, database declaration, module build list, or roots does.

## What the SHA does not mean

Matching declaration SHA values do **not** establish that any of these are unchanged:

- project source files;
- build tags;
- GOOS / GOARCH / CGO state;
- compiler flags or other build environment;
- local replacement source contents;
- generated files;
- static call-graph results;
- runtime/data-flow behavior;
- exploitability.

The serialized contract therefore states:

```text
scope = govulncheck-scan-declaration
freshness = not-established
source_state_fingerprint = false
build_configuration_fingerprint = false
```

This identity can later associate a symbol report with the exact scanner-declared module/root inventory. It must not be reused as the future symbol-evidence freshness check.

## Scan SBOM trust boundary

The pre-public parser now requires exactly one govulncheck SBOM message for accepted source-symbol output.

The retained SBOM must provide at least one root package and valid module path identities. Strict symbol correlation additionally requires the vulnerable symbol frame's module/version to exist in the scanner-declared SBOM build list before UPM attaches that finding to an existing Go advisory impact.

That makes the correlation chain:

```text
validated govulncheck protocol
  -> scanner-declared source/symbol mode + local DB
  -> scanner-declared scan SBOM build list
  -> govulncheck OSV/alias identity
  -> UPM exact component + effective module + version
```

A contradiction at any layer remains unmatched/invalid instead of being guessed through.

## Validation

Focused driver:

```sh
sh ./scripts/test-go-symbol-scan-declaration.sh
```

The dedicated identity tests cover deterministic ordering, sensitivity to scanner/DB/build-list changes, retained Go/DB metadata, explicit non-freshness semantics, and refusal when scan SBOM evidence is absent.

This primitive remains pre-public and does not add a CLI route, persisted evidence, or status freshness state.
