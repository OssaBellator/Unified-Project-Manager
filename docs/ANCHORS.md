# Local anchor semantics

UPM exposes deterministic hashes for local evidence sets so an external trust system can record them. UPM does **not** claim those local hashes are externally authenticated by themselves.

There are currently two related anchorable structures:

- `.upm/receipt-chain.json` — ordered exact v2 mutation-receipt identities;
- `.upm/evidence-manifest.json` — byte-level hashes for the current known UPM evidence set.

## Stable identity versus generation time

Both structures contain a human-useful generation timestamp, but their stable set identity deliberately excludes that timestamp.

This distinction is intentional:

- rebuilding the same receipt/evidence set at a later clock time should not produce a different set identity merely because the command was rerun;
- the stable hash answers **what exact evidence set is this?**, not **when did somebody first observe it?**

Therefore a timestamp printed inside a local chain/manifest must not be interpreted as authenticated by the stable set/head digest unless an external system separately binds the complete file bytes or timestamp.

For the receipt chain:

- each chain entry binds sequence, previous chain hash, exact v2 `receipt_id`, and root-relative receipt path;
- the final `head_hash` is stable for that exact ordered receipt set;
- the canonical anchor digest binds version, head, and entries;
- generation time is display metadata, not part of that stable set identity.

For the project evidence manifest:

- `evidence_set_id` binds version plus the sorted artifact table (`path`, `kind`, `sha256`, `size`);
- the canonical anchor digest binds version, evidence-set ID, and artifact table;
- generation time is display metadata, not part of the stable evidence-set identity.

If generation time itself is part of the security requirement, anchor/sign the complete manifest bytes (or a separate statement containing the stable digest plus trusted timestamp) in the external trust system.

## Why UPM does not sign automatically

Automatic signing would require choosing or managing a trust root, private key, OS keychain identity, transparency service, or organization signing policy. Those are deployment policy decisions, not package-manager semantics.

UPM instead provides deterministic material that such systems can consume:

- receipt-chain head/anchor digest;
- evidence-manifest evidence-set ID/anchor digest;
- v2 advisory evidence ID;
- v2 mutation receipt IDs.

## Re-anchoring

A newly created legitimate receipt or evidence artifact invalidates an older local anchor because the evidence set changed. Re-anchoring is explicit rather than automatic.

This prevents a mutation command from silently updating the very anchor that was intended to detect changes to the previous evidence set.

## Threat boundary

Local validation catches accidental corruption, partial edits, stale anchored sets, and many forms of inconsistent tampering.

An attacker who can rewrite the entire project evidence store and then generate a new internally consistent anchor can create a new local history. Protection against that attacker requires a trust boundary outside the writable project tree.

UPM must not report `authenticated=true` unless such an external trust relationship is actually implemented and verified.