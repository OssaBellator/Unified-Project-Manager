# Contributing

UPM is a control plane over native project/package managers; it is **not another resolver**. Contributions should keep native tools and native state authoritative.

## Expectations

- Preserve preview-before-mutation and explicit network boundaries.
- Refuse ambiguous manager/component/workspace ownership rather than guessing.
- Keep provider-specific uncertainty visible.
- Record applied mutations truthfully; do not overstate receipt scope.
- Add focused tests for provider, security, receipt, workspace, or fleet behavior that changes.

Run the aggregate local validation:

```sh
sh ./scripts/check-all-local-latest.sh
```

Useful focused suites include:

```sh
sh ./scripts/test-native-security.sh
sh ./scripts/test-integration.sh
sh ./scripts/test-fleet-providers.sh
```

Architecture and provider contracts live under [docs/](./docs/). Security-sensitive reports should follow [SECURITY.md](./SECURITY.md).
