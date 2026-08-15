# Native dependency update semantics

`update` is intentionally **not** a universal resolver operation in UPM.

UPM selects the authoritative project component/manager, previews the exact native argv, describes the classes of state the native command may change, and delegates resolution to that manager. UPM does not calculate a cross-ecosystem target version or rewrite native dependency constraints itself.

## Common control-plane behavior

The update surface is preview-first. Applied updates use the same mutation-evidence model as other UPM package operations:

- exact component/manager ownership checks;
- argv execution without a shell;
- exact executable resolution by the native runner;
- optional post-operation doctor verification;
- a v2 `project-native-state` mutation receipt;
- before/after native manifest/lock-state hashes;
- partial-state evidence even when the native update exits non-zero.

Preview metadata declares four independent side-effect classes:

- `manifest_may_change`;
- `native_state_may_change`;
- `installed_state_may_change`;
- `network_may_be_used`.

These fields are not interchangeable. For example, a lock-only update is different from updating an installed environment.

## npm

UPM delegates to:

```text
npm update [package...]
```

The UPM contract treats this as an update of dependency resolutions within the project's declared constraints. Native lock and installed state may change; UPM does not intentionally rewrite the declared `package.json` ranges itself.

## pnpm

UPM delegates to:

```text
pnpm update [package...]
```

Native pnpm resolution remains authoritative. Lock and installed state may change.

## Yarn

Yarn is version-sensitive.

For a project explicitly declaring Yarn Classic (`yarn@1.x`), UPM uses:

```text
yarn upgrade [package...]
```

For modern Yarn, UPM uses:

```text
yarn up [pattern...]
```

A modern all-dependency update is represented as argv containing the literal `*` pattern. UPM does not involve a shell, so the pattern is not expanded into filenames by the host shell.

Yarn update behavior may rewrite manifest and lock/install state according to the selected Yarn version's native semantics.

## Bun

UPM delegates to:

```text
bun update [package...]
```

Bun remains authoritative for manifest/lock/install behavior.

## uv

UPM deliberately separates **updating the lock resolution** from **synchronizing the environment**.

All locked packages:

```text
uv lock --upgrade
```

Selected packages:

```text
uv lock --upgrade-package package-a --upgrade-package package-b
```

This update operation is modeled as native lock-state mutation. It does not imply that the local Python environment has been synchronized to the new lock. Environment synchronization remains a separate explicit UPM/native operation.

## Poetry

UPM delegates to:

```text
poetry update [package...]
```

Poetry remains authoritative for constraint interpretation, lock changes, and environment updates.

## PDM

UPM delegates to:

```text
pdm update [package...]
```

PDM remains authoritative for constraint interpretation, lock changes, and environment updates.

## Cargo

All packages:

```text
cargo update
```

Selected packages are expressed using repeated package selectors:

```text
cargo update -p serde -p syn@2.0.0
```

UPM models Cargo update as changing `Cargo.lock` selections while respecting `Cargo.toml` requirements. It does not describe that operation as an installed-environment update.

## Go

UPM intentionally refuses a generic no-target Go update.

A repository-wide `go get -u ./...` style policy can have broad source/module consequences and is not equivalent to the update semantics of npm/Cargo/uv. UPM therefore requires the user to name explicit module/package targets.

A target without an explicit `@version` is normalized to `@latest`:

```text
upm update golang.org/x/text
```

plans native argv equivalent to:

```text
go get golang.org/x/text@latest
```

An explicit version is preserved:

```text
go get example.com/lib@v1.2.3
```

Go module files may change; there is no separate installed project environment implied by this operation.

## pip

UPM refuses a generic pip update operation.

`pip install --upgrade ...` updates an environment, but by itself it does not provide a safe authoritative mutation of project desired state in `pyproject.toml` or requirements constraints. Treating it as the same operation as a lock-aware project manager would create false consistency.

Use a pyproject-aware manager or an explicit native workflow when pip is the only available tool.

## Network behavior

Native updates commonly need package registries/proxies and are marked `network_may_be_used = true` in the plan. Preview performs no native update and writes no receipt.

The network flag describes the delegated manager command; it is not a guarantee that network access will occur on every execution (a manager may satisfy an operation entirely from local state/cache).

## Non-goals

UPM update does not:

- choose a universal "best" version across ecosystems;
- translate semver/PEP 440/Cargo/Go constraints into one resolver language;
- silently update every Go dependency;
- treat lock mutation as equivalent to installed-environment mutation;
- treat environment-only pip upgrades as project desired-state updates;
- automatically accept resulting project-state changes without recording them.
