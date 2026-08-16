from __future__ import annotations

from collections.abc import Mapping

from .go_symbol_source_observation import GoSymbolSourceObservation


GO_SYMBOL_GOENV_DISABLED = "off"


def environment_with_persisted_go_config_disabled(
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Return an environment that disables persisted `go env -w` configuration.

    `GOENV=off` prevents Go commands from reading the per-user Go environment
    configuration file. Explicit process settings such as GOFLAGS are preserved
    so separate fail-closed checks can still reject them rather than silently
    normalizing user-selected build behavior.
    """

    result = dict(environment)
    for key in tuple(result):
        if key.upper() == "GOENV":
            result.pop(key, None)
    result["GOENV"] = GO_SYMBOL_GOENV_DISABLED
    return result


def go_symbol_effective_goflags_blocker(
    observation: GoSymbolSourceObservation,
) -> str | None:
    """Return a fail-closed reason when effective GOFLAGS is not exactly empty.

    The source observation obtains this value from the same `go env -json`
    invocation that precedes package loading. Requiring an explicit empty value
    prevents real scanner-alignment gates from treating argv-only `tags=[]` as
    complete build-selection evidence when process or persisted Go configuration
    may inject default flags.
    """

    value = observation.build_environment.get("GOFLAGS")
    if value is None:
        return (
            "Go source observation is missing effective GOFLAGS; "
            "real scanner build-selection equivalence is not established"
        )
    if value:
        return (
            f"effective Go GOFLAGS is {value!r}, not empty; "
            "real scanner alignment does not override user GOFLAGS"
        )
    return None
