# Mutation receipts

UPM's mutation receipt layer records what a delegated native operation actually changed without becoming a rollback engine or a second dependency lockfile.

## Why receipts exist

A package manager command can fail after changing files. “Non-zero exit status” does not imply “no mutation happened.” A control plane therefore needs a post-operation observation, not only a command log.

Receipts provide:

- the operation name;
- redacted native argv;
- component/manager/cwd identity;
- command return codes;
- SHA-256 + size observations of manifests/native state before execution;
- the same observations after execution;
- added/removed/changed/unchanged state-file deltas;
- optional post-operation verification metadata.

The generic execution wrapper stops a batch on the first non-zero result but still re-discovers state and writes the partial-mutation receipt.

## Privacy boundary

Receipts deliberately do **not** persist:

- stdout;
- stderr;
- environment variables;
- package contents.

Common token/password/auth argv forms are redacted before persistence. This is a defensive filter, not a guarantee that arbitrary user-supplied command arguments can never contain sensitive data; callers should avoid putting secrets on command lines in the first place.

## Storage

Default receipt location:

```text
.upm/receipts/<timestamp>-<receipt-id-prefix>.json
```

Writes are atomic (`.tmp` + replace).

Receipt state paths are project-relative. Extra native state may be included explicitly, but paths outside the project root are rejected.

## Drift and consistency

The receipt-history layer can:

- recompute the receipt ID from canonical core content;
- recompute the change list from before/after observations;
- validate `succeeded` against recorded command return codes;
- compare current project state with the latest valid successful receipt baseline;
- report invalid receipts separately from native-state drift.

This supports states such as `current`, `drifted`, `absent`, and invalid-history conditions.

## What receipts do not prove

Receipts are **tamper-evident local consistency evidence**, not cryptographic authenticity.

Without signing or an external/immutable anchor, UPM cannot prove:

- who created a receipt;
- that a malicious actor did not rewrite both state and receipts;
- that receipt files were never deleted;
- that a command produced only the recorded filesystem effects outside the observed native-state set.

UPM should not use local receipt hashes as a substitute for signed provenance/attestation.

## Rollback boundary

Receipts do not imply transactional rollback. Native package managers may alter files, caches, environments, hooks, generated assets, or external state that cannot be safely reversed from manifest/lock hashes.

A future repair/rollback feature should therefore consume ecosystem-specific capabilities and explicit backups rather than treating a receipt as an undo log.
