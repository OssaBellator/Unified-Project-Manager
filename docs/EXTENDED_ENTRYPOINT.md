# Extended local entrypoint

Several newer control-plane capabilities were developed behind focused standalone modules while the central installed dispatcher could not be safely replaced through the repository connector. Leaving those modules disconnected would create integration debt, so the branch now includes one additive integration bridge:

```text
python -m unified_project_manager.extended_entrypoint ...
```

For a repository checkout, the helper script is:

```sh
sh ./scripts/upm-dev.sh ...
```

The helper sets `PYTHONPATH=src` and invokes the extended entrypoint. It does not install the package or use GitHub Actions.

## Routing model

The extended entrypoint handles the mature additive commands first:

- `update`
- `dedupe`
- `env`
- `duplicates`
- `duplicates-physical`
- `tools`
- `tools-state`
- `audit-v2`
- `advisory-v2-status`
- `evidence manifest`
- `evidence validate`
- `evidence verify`

Any command not owned by the additive bridge is passed unchanged to the existing `root_entrypoint.main()` implementation. This means existing commands continue using their established parser/behavior rather than being reimplemented in the bridge.

## Why this is additive instead of replacing the installed console entrypoint immediately

The package already has a large command surface. Replacing the installed root dispatcher without reading its exact current blob would risk dropping or shadowing existing routes.

The bridge therefore gives development checkouts one unified command namespace while keeping promotion to the normal `upm` console script as a small, reviewable follow-up once the central dispatcher can be safely edited and the combined test suite can be run from a real checkout.

## Safety semantics remain command-specific

The bridge does not weaken preview/network/mutation boundaries. For example:

- `tools` defaults to executable-path resolution with no tool execution; version probes require `--probe-versions`;
- `duplicates-physical` hashes files only on explicit invocation and never deletes anything;
- `update` and `dedupe` remain preview-first and receipt-backed when applied;
- `audit-v2` remains preview-first because applying it can use advisory/network services;
- evidence validation is local/read-only.

## Promotion criteria

Before changing the package's primary console entrypoint to this routing layer, the branch should satisfy all of the following on a real local checkout:

1. `sh ./scripts/check.sh` passes the complete suite;
2. focused extended/safety runners pass;
3. existing root-entrypoint commands retain their routes and exit semantics;
4. no GitHub Actions workflow is required;
5. prototype modules that have been superseded are either removed or clearly not routed/documented as canonical.

Until then, `scripts/upm-dev.sh` is the branch-local integration surface for the newly added commands.