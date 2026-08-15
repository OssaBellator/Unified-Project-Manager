# Physical duplicate content analysis

UPM's normalized duplicate reports answer dependency-graph questions. They do **not** prove that repeated package observations consume repeated physical disk bytes.

Physical duplicate content analysis is therefore a separate, explicit, potentially expensive read-only operation.

## Scope

The scanner only walks known **project-local artifact roots** for discovered components:

- Node: `node_modules/`;
- Python: `.venv/` and `__pypackages__/`;
- Rust: `target/`;
- Go: `vendor/`.

It does not crawl the entire project, home directory, system package locations, or machine-wide package caches. Shared native caches/stores have separate storage/provenance commands.

## Symlink safety

Artifact-root symlinks are rejected before path resolution. Directory symlinks inside an artifact root are not followed. File symlinks are not opened or hashed.

This prevents a project-local scan from unintentionally traversing arbitrary external files through a symlinked environment/artifact tree.

## Physical identity

The scanner first groups regular files by physical filesystem identity where a usable inode is available.

Multiple paths pointing at the same physical inode are reported as **hardlink/shared-byte observations**:

- they represent one physical file instance;
- their `duplicate_content_bytes` is zero;
- they are not treated as repeated physical content.

On filesystems/platforms where a usable inode identity is unavailable, UPM falls back to per-path physical identity. It never collapses unrelated files merely because an inode sentinel such as `0` repeats.

## Hashing strategy

The scan is intentionally explicit because hashing package/build trees can be expensive.

To reduce unnecessary I/O:

1. symlinks/non-regular files are skipped;
2. files below `--min-size-bytes` are ignored;
3. remaining files are grouped by size;
4. SHA-256 is computed only for size groups containing at least two distinct physical instances;
5. each physical inode is hashed once even when it has multiple hardlink aliases.

The default minimum size is 4096 bytes. Set a lower threshold when complete small-file coverage is worth the extra I/O.

## Duplicate-content groups

A duplicate-content group requires:

- equal file size;
- equal SHA-256;
- at least two distinct physical file identities.

For a group containing `N` physical instances of a file of size `S`, UPM reports:

```text
duplicate_content_bytes = S * (N - 1)
```

This is an **observational repeated-content byte count**, not a reclaimable-byte guarantee.

## Why repeated bytes are not automatically reclaimable

Identical file content can still be intentionally required at multiple independent paths because of:

- isolated dependency environments;
- build output layout;
- package-manager ownership expectations;
- writable-vs-read-only lifecycle differences;
- permissions/metadata not represented by content hash;
- future independent mutation;
- container/workspace boundaries.

Replacing copies with hardlinks, deleting one path, or moving content into a content-addressed store can change semantics even when bytes are currently identical.

UPM therefore reports:

```json
{"reclaimable": false}
```

at both report and duplicate-group level.

## Strict mode

Strict mode can be used as a reporting gate when repeated physical content groups are present.

Hardlink/shared-byte observations do not fail strict mode because they already represent one physical copy.

Strict mode still performs no deletion/linking/rewriting.

## Relationship to native dedupe

Physical repeated content and native dependency deduplication are different layers:

- native `npm/pnpm/Yarn dedupe` asks a resolver/manager to converge a dependency tree under its own rules;
- physical scanning observes identical bytes after whatever native layout exists.

One does not imply the other. UPM never uses physical hashes to synthesize a dependency-resolution mutation.

## Non-goals

The scanner does not:

- hash the whole filesystem;
- follow symlinks;
- scan shared package caches by default;
- declare duplicate-content bytes reclaimable;
- automatically replace copies with hardlinks/reflinks;
- delete build/package files;
- infer package identity solely from file content.

It is an expensive-but-contained measurement layer for answering the narrower question: **where do known project-local artifact trees contain the same bytes on more than one physical file identity?**