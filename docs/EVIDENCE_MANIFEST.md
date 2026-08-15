# Project evidence manifest

UPM accumulates several kinds of local evidence under `.upm/`: integrity snapshots, advisory evidence, mutation receipts, and optional receipt-chain anchors. Those files answer different questions and intentionally remain separate.

The project evidence manifest provides one additional layer: a deterministic root-relative hash set over the evidence artifacts that already exist.

## Purpose

A manifest makes it possible to say:

> This exact set of UPM evidence files had these hashes and sizes.

It gives an external trust system one stable digest to record without requiring that system to understand every UPM evidence schema.

It does **not** turn UPM into the external trust system.

## Included artifacts

Version 1 discovers the following local evidence when present:

- `.upm/state.json` — portable project integrity snapshot;
- `.upm/audits/osv.json` — compatibility advisory evidence;
- `.upm/audits/osv-v2.json` — stronger self-validating advisory evidence;
- `.upm/receipt-chain.json` — optional receipt-chain manifest;
- every regular `.json` file under `.upm/receipts/` — mutation receipts.

The evidence manifest deliberately does not include itself, avoiding recursive identity.

Symlinked evidence artifacts are not followed or included.

## Artifact identity

Each artifact records:

- root-relative path;
- evidence kind;
- SHA-256 of file bytes;
- byte size.

The artifact table is sorted deterministically.

## Evidence-set ID

`evidence_set_id` is SHA-256 over the canonical versioned artifact table. The generation timestamp is not part of that identity, so rebuilding the manifest at two different times with unchanged evidence produces the same evidence-set ID.

The manifest also exposes an anchor digest over its canonical stable representation. An external transparency log, signing workflow, or other trust service can store that digest if desired.

## Validation

Validation compares the anchored artifact table with the current known evidence set and reports:

- `missing` — an anchored evidence file no longer exists;
- `changed` — path exists but kind/hash/size differs;
- `unexpected` — a newly discovered evidence file was not in the manifest.

The manifest's own evidence-set ID is recomputed before current-state comparison. Editing the artifact table without changing the ID therefore makes the manifest invalid immediately.

A newly created legitimate receipt or advisory evidence file makes an older evidence manifest stale/unexpected until explicitly rebuilt. This is intentional: anchoring applies to one exact evidence set.

## Trust boundary

Like the local receipt chain, the evidence manifest is tamper-evident but not externally authenticated.

An actor able to rewrite every local evidence artifact and then create a new evidence manifest can produce a new self-consistent local state. External authentication only exists if the manifest/anchor digest is recorded by a trust system outside that rewrite boundary.

UPM must not claim otherwise.

## Relationship to receipt chains

The receipt chain and evidence manifest solve different problems:

- the receipt chain binds ordered mutation-receipt identities and detects history-set changes;
- the evidence manifest binds the byte-level state of multiple UPM evidence classes.

A project may use neither, one, or both. If both exist, the evidence manifest hashes the receipt-chain file as one artifact while also hashing the underlying receipt files themselves.

## Non-goals

The evidence manifest does not:

- replace ecosystem dependency lockfiles;
- make stale advisory evidence current;
- prove that a vulnerability is exploitable;
- prove that a receipt captured arbitrary filesystem or remote side effects;
- automatically sign or publish anything;
- upload local evidence anywhere.

It is a deterministic local evidence-set description designed to be composable with a real external anchor when one is available.