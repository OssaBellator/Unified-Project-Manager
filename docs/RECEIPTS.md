# Mutation receipt evidence contract

UPM mutation receipts are local evidence about **native project state**. They are not a universal filesystem transaction log and they are not an external attestation system.

## What a receipt observes

For a selected project root, UPM records native files already represented by discovery:

- component manifests;
- component native lock/checksum/state files;
- explicitly supplied in-root native state, such as files touched by an internal `go work sync`.

Each observation records the root-relative path, evidence kind, SHA-256, and byte size. After execution, UPM rediscovers the project and records the same state class again. Added, removed, changed, and unchanged entries are derived from those before/after observations.

A receipt therefore answers questions such as:

- which native manifests or lock/state files changed during an applied operation;
- which native command was delegated and what return code it produced;
- whether the project passed the configured post-operation verification;
- whether the current native state still matches the latest successful receipt baseline.

It does **not** claim to capture arbitrary source/build outputs, user-level package-manager configuration, environment variables, remote side effects, or machine-wide cache mutations.

## Preview and failure behavior

Preview-only commands do not create receipts.

Applied package operations, workspace-aware package batches, initialization, repair, native-manager `exec`, and in-root Go workspace synchronization persist receipts. A non-zero native command still produces a receipt after rediscovery so partial native-state changes are retained as evidence.

Machine-wide cache maintenance intentionally uses cache-specific plans rather than project receipts.

User-authored task DAGs may create arbitrary outputs outside the native package-state model, so UPM does not describe task execution as a complete mutation receipt.

## Argument redaction

Receipt argv is redacted before persistence for recognized token/password/secret/authentication flag and assignment forms. Redaction reduces accidental credential persistence; it is not a substitute for avoiding secrets in command-line arguments.

The working directory is stored root-relative when possible. An out-of-root command working directory is represented as `<outside-project>` rather than persisting an unrelated absolute path.

## Receipt versions

### v1

The original receipt identity bound:

- operation;
- redacted command records;
- before observations;
- after observations;
- creation time.

Post-operation verification was persisted but was not part of the receipt ID. UPM continues to validate v1 files against that historical identity algorithm so existing local evidence remains readable.

A v1 receipt is **not eligible for new receipt-chain anchoring**, because a chain cannot retroactively provide integrity guarantees for fields the original receipt ID did not bind.

### v2

New receipts use version 2. The canonical receipt ID additionally binds:

- the receipt schema version;
- the persisted verification payload.

Derived fields such as `succeeded` and the state-change list are recomputed during validation from identity-bound commands and before/after observations rather than independently trusted.

Changing verification content in a v2 file without recomputing the receipt ID makes the receipt invalid. Rewriting the receipt into a different self-consistent v2 receipt changes its receipt ID.

## Receipt history

`upm receipts` validates every receipt file and compares current discovered native state to the latest valid successful receipt baseline.

Typical states include:

- `absent` — no receipt history exists;
- `current` — native project state matches the latest valid successful receipt;
- `drifted` — current native state differs from that baseline;
- invalid-history states — one or more receipt files cannot be trusted as continuous history.

Receipt absence is optional by default. Drift or invalid history is a status blocker because persisted evidence exists and no longer matches the native project state/history it describes.

## Optional receipt chain

`upm receipts chain` builds a deterministic hash chain over the exact v2 receipt identities and root-relative receipt paths.

Preview computes:

- ordered chain entries;
- the proposed head hash;
- a canonical SHA-256 anchor digest.

`--apply` writes `.upm/receipt-chain.json`.

Chain validation checks:

- entry ordering and hash linkage;
- anchored receipt paths still exist;
- no unexpected receipt files were added after anchoring;
- every current receipt is individually valid v2 evidence;
- the current receipt ID at each anchored path is exactly the receipt ID that was anchored.

The last check is important: replacing an anchored receipt with a different self-consistent receipt at the same filename must invalidate the chain.

A new legitimate receipt also invalidates an older chain until the user explicitly re-anchors the expanded receipt set. This is intentional; anchoring represents an explicit statement about a particular history set.

## Trust boundary of the local chain

The chain is **tamper-evident, not externally authenticated**.

An actor able to rewrite all local receipts and the chain manifest could construct another internally consistent local history. UPM therefore exposes the deterministic anchor digest so another trust system can record it, but UPM does not claim an external witness exists unless one is actually integrated by the user/environment.

## Out-of-root Go workspace members

`go work sync` can update member `go.mod` files outside the selected project root when the user explicitly supplies `--allow-external`.

UPM intentionally does not write a project mutation receipt for that execution. A receipt containing only the in-root subset would falsely imply complete coverage of the native command's mutation scope. The command instead reports:

- `receipt = null`;
- `receipt_scope = external-unrepresented`;
- an explanation of why a complete project-root receipt cannot be produced;
- the native changed-file report.

Internal-only workspace sync remains fully receipt-backed.

## Non-goals

Mutation receipts do not:

- replace ecosystem lockfiles;
- restore arbitrary package-manager/cache side effects;
- prove runtime reproducibility;
- prove source/API exploitability;
- automatically roll back a failed package-manager command;
- make a local chain externally trustworthy on their own.

They are deliberately scoped evidence that UPM can validate and compose with doctor, workspace, policy, advisory, and integrity-snapshot state.