# Security, advisory, and cache safety model

UPM separates project integrity, advisory intelligence, cache verification, storage measurement, and destructive cache maintenance. They are related control-plane concerns but they do not have the same evidence or mutation guarantees.

## Integrity layers

UPM treats these as distinct layers:

1. **Project structure/state** — manifests, manager ownership, native state syntax, tool availability/version drift.
2. **Portable snapshot integrity** — `.upm/state.json` SHA-256 observations of reviewed native project-state files.
3. **Native semantic verification** — authoritative manager/toolchain checks for lock/project consistency.
4. **Installed-state drift** — optional physical environment inspection (`doctor --deep`).
5. **Shared package/cache integrity** — ecosystem-native content/store checks.
6. **Advisory intelligence** — known-vulnerability lookup over concrete package identities.
7. **Storage measurement** — byte/file observations only.
8. **Cache maintenance** — explicit native prune/clean commands.

A finding at one layer is not automatically repairable at another.

## Advisory scanning

`upm audit` is preview-first because OSV-Scanner may use network access and therefore dependency inventory may leave the local machine.

The applied flow is:

1. discover the project;
2. generate a temporary CycloneDX 1.7 SBOM from UPM's concrete inventory;
3. optionally enrich selected Go modules when `--native-go` is requested;
4. resolve the exact `osv-scanner` executable;
5. invoke OSV-Scanner against the temporary `.cdx.json` file;
6. parse JSON results;
7. remove the temporary directory/SBOM.

OSV-Scanner exit status `1` is treated as “findings present,” not tool failure. Scanner/invocation failure remains a separate error class.

`upm projects audit` applies the same preview-first model to explicitly registered projects. A missing/unscannable project is reported independently rather than aborting preview of the remaining fleet.

Advisory scanning is **not** a source-code exploitability analysis. A known vulnerable package can be correlated with native dependency paths, but that still does not prove a vulnerable function is imported, called, or reachable at runtime.

## Advisory path correlation

The `security_impact` layer can correlate package findings with relationship evidence from:

- npm logical lock-tree paths;
- locked/offline Cargo dependency paths;
- Go module requirement paths;
- unambiguous uv universal-lock paths.

Every correlated result retains provider and scope labels. Ambiguous uv fork references are not turned into fabricated paths.

## Cache integrity

Cache/store verification is ecosystem-specific.

### Go

Project-context Go module-cache verification uses `go mod verify` with temporary adjacent module files so the real project `go.mod` / `go.sum` are isolated from writes. The Go tool may still populate shared-cache metadata while resolving cached module state.

### pnpm

`pnpm store status` is treated as a non-mutating shared-store integrity check.

### npm

`npm cache verify` is not grouped with read-only checks because npm may garbage-collect unneeded cache entries as part of verification. UPM therefore makes it preview/apply maintenance verification.

## Storage is not cleanup advice

Project/fleet storage and global cache storage report observed bytes/files. They intentionally do not calculate a generic “safe to reclaim” number.

Hardlinks are deduplicated where filesystem inode identity is available. Symlinks are not followed.

Known global cache/store providers include Go, npm, pnpm, uv, and Cargo. Shared caches are machine-scoped; they are not charged to every project merely because multiple projects use them.

## Explicit cache maintenance

UPM never infers destructive action from a storage report.

`upm cache prune` is preview-first for manager-defined unused/unreferenced cleanup:

- `pnpm store prune`;
- `uv cache prune`.

`upm cache clean` is a stronger explicit full-cache action:

- npm: `npm cache clean --force`;
- Go build cache: `go clean -cache`;
- Go module cache: `go clean -modcache`.

Go full cleaning requires an explicit cache category. Every maintenance plan says that data may need to be downloaded or rebuilt again later.

These commands do not use measured byte counts as deletion targets, and UPM does not directly unlink manager-owned cache files.

## Privacy defaults

The intended control-plane defaults are:

- local/static inspection where possible;
- preview before mutation or network-capable advisory execution;
- offline native graph providers where the ecosystem provides a reliable mode (Cargo is explicitly `--offline`);
- no automatic home-directory crawling;
- no advisory upload/network call merely to render `status` or `policy`;
- no cache cleaning triggered by doctor, status, policy, or storage measurement.

Go graph queries are being hardened toward cache-only/offline-by-default execution as a separate provider-safety improvement; read-only module-file semantics alone must not be confused with a zero-network guarantee.

## Policy boundary

Project/fleet policy is enforcement-only. It can require integrity/verifier coverage and constrain managers/error budgets, but it does not execute advisory scans or destructive cache maintenance just to make a policy pass.

Future advisory policy should therefore be based on explicit scan artifacts/results or an explicitly requested scan, not a hidden network call during ordinary status evaluation.
