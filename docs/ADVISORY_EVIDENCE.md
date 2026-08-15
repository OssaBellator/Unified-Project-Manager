# Persisted advisory evidence

UPM keeps advisory scanning and advisory enforcement separate.

Scanning may use network access. Ordinary `status` and `policy` must not silently make the same network request again merely to decide whether a project is healthy.

The evidence layer provides a local bridge between those two concerns.

## Evidence artifact

The default evidence path is:

```text
.upm/audits/osv.json
```

Version 1 records:

- scanner identity;
- UTC generation time;
- SHA-256 fingerprint of the exact canonical SBOM that was scanned;
- package count;
- inventory mode;
- scanner return code;
- vulnerable/clean state;
- affected-package and unique-vulnerability counts;
- the machine-readable scanner report.

Writes are atomic (`.tmp` + replace).

## Why the SBOM fingerprint matters

A “clean yesterday” result is not evidence for a different dependency set today.

For static resolved inventory, UPM regenerates the current local SBOM without network access and compares its SHA-256 fingerprint with the persisted scan artifact.

If dependencies change, the evidence becomes `stale` immediately even if its timestamp is recent.

This prevents policy from treating an old clean scan as valid merely because the file still exists.

## Local evidence states

The local evaluator has explicit states:

- `absent` — no persisted evidence exists;
- `current-clean` — fingerprint matches and the scan reported no known vulnerabilities;
- `current-vulnerable` — fingerprint matches and the scan reported known vulnerabilities;
- `stale` — dependency fingerprint changed or the configured age budget was exceeded;
- `native-inventory-unverified` — the scan used native enrichment that ordinary local status deliberately refuses to re-execute;
- `invalid` — evidence is malformed or unsupported.

`current-vulnerable` is current evidence, but it does not pass a zero-vulnerability policy.

## Native-enriched evidence

A native-enriched scan can contain stronger inventory than static lock parsing, for example authoritative selected Go modules.

Ordinary local status does **not** silently rerun native graph commands to verify that fingerprint. Such evidence is therefore labeled `native-inventory-unverified` until an explicitly requested native refresh/scan is performed.

This avoids turning `status` into a hidden command execution or network boundary.

## Policy

The policy layer can enforce persisted evidence without scanning:

```toml
[policy]
require_advisory_evidence = true
max_advisory_age_seconds = 86400
max_known_vulnerabilities = 0
```

Semantics:

- `require_advisory_evidence` requires current locally verifiable evidence;
- `max_advisory_age_seconds` makes older evidence stale;
- `max_known_vulnerabilities` evaluates the count recorded by current evidence.

A vulnerability budget cannot be evaluated from absent/stale/unverified evidence; that is an explicit policy violation rather than an assumed zero.

## What evidence does not prove

Persisted OSV evidence records known advisory matches against package identities. Even when UPM can correlate a finding with a dependency path, it does **not** prove:

- the vulnerable function is imported;
- the vulnerable code path is called;
- the condition is exploitable in this project;
- the dependency is active on the current runtime/platform;
- an advisory database is complete.

Those require stronger source/runtime analysis and should remain separate evidence classes.

## Intended workflow

The intended control-plane workflow is:

1. preview an advisory scan;
2. explicitly execute it when network disclosure is acceptable;
3. persist the exact scan evidence;
4. let local policy/status consume that artifact without rescanning;
5. invalidate it automatically when the scanned dependency fingerprint changes;
6. explicitly refresh scans when evidence is stale or native inventory must be revalidated.

This keeps network access visible while still making advisory hygiene enforceable in local development and external CI systems that call UPM's local scripts.
